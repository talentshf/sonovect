"""Pinned model preparation and verification, usable inside role images or Python.

No inference code is downloaded. Offline verification never writes cache files.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

_VERIFIED = {}


def catalog():
    return json.loads(Path(__file__).with_name("model-catalog.json").read_text())["models"]


def unconfirmed_licenses(aliases):
    """Published declarations only; acknowledgement does not grant model rights."""
    models = catalog()
    return sorted(a for a in aliases if models[a].get("license") not in {"Apache-2.0", "BSD-3-Clause"})


def component_license_metadata(aliases):
    """Describe selected upstream terms without gating assembly or granting rights."""
    aliases = tuple(aliases)
    return {"component_license_policy": "informational",
            "unconfirmed_model_licenses": unconfirmed_licenses(aliases),
            "unconfirmed_runtime_licenses": ["moss-audio-license-text"]
            if any(alias in {"moss-4b", "moss-8b"} for alias in aliases) else []}


def verify(root, model):
    root = Path(root)
    def fingerprint():
        values = []
        for name in model["files"]:
            try:
                s = (root / name).stat()
            except FileNotFoundError:
                raise RuntimeError("model_file_missing_or_wrong_size:" + name) from None
            values.append((name, s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns))
        return tuple(values)
    key = (str(root.resolve()), json.dumps(model["files"], sort_keys=True))
    before = fingerprint()
    if _VERIFIED.get(key) == before:
        return str(root)
    for name, expected in model["files"].items():
        path = root / name
        if not path.is_file() or path.stat().st_size != expected["size"]:
            raise RuntimeError("model_file_missing_or_wrong_size:" + name)
        h = hashlib.sha256() if expected["algorithm"] == "sha256" else hashlib.sha1()
        if expected["algorithm"] == "git-sha1":
            h.update(f"blob {expected['size']}\0".encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024**2), b""):
                h.update(block)
        if h.hexdigest() != expected["digest"]:
            raise RuntimeError("model_file_digest_mismatch:" + name)
    if fingerprint() != before:
        raise RuntimeError("model_changed_during_verification")
    _VERIFIED[key] = before
    return str(root)


def storage_plan(aliases, cache=None):
    """Read-only, hash-aware capacity plan for the SDK layouts pinned by this release.

    Unknown layouts are conservatively charged as missing. Files are never created
    or downloaded here; shared filesystems are aggregated by the caller.
    """
    import shutil
    records = []
    for alias in aliases:
        model = catalog()[alias]
        if model["hub"] == "huggingface":
            base = Path(cache or os.getenv("HF_HUB_CACHE") or
                        str(Path(os.getenv("HF_HOME", str(Path.home()/".cache/huggingface")))/"hub"))
            repo = base / ("models--" + model["repo_id"].replace("/", "--"))
            roots = [repo / "snapshots" / model["revision"]]
        else:
            base = Path(cache or os.getenv("MODELSCOPE_CACHE", str(Path.home()/".cache/modelscope")))
            owner, name = model["repo_id"].split("/", 1)
            snapshot = base/"models"/(owner+"--"+name)/"snapshots"/model["revision"]
            known = [snapshot.parents[1], base/"models"/owner/name.replace(".", "___")]
            legacy = [base/owner/name, base/owner/name.replace(".", "___"),
                      base/"hub"/owner/name, base/"hub"/owner/name.replace(".", "___"),
                      base/"models"/owner/name]
            def populated(path):
                return path.is_dir() and next(path.iterdir(), None) is not None
            direct = base/"models"/model["repo_id"]
            if alias in {"fsmn", "cam"} and direct.is_dir():
                roots = [direct]  # resolve()'s verified fixed-cache fast path.
            else:
                override = None if any(populated(p) for p in known) else next(
                    (p for p in legacy if populated(p)), None)
                sdk_legacy = [known[1], base/"hub"/"models"/owner/name.replace(".", "___")]
                roots = [override or next((p for p in sdk_legacy if populated(p)), snapshot)]
        # Follow the pinned SDK's active layout. A complete but shadowed old
        # snapshot must not hide missing bytes in the directory it will use.
        best = []
        for root in roots:
            valid = []
            for name, expected in model["files"].items():
                try:
                    verify(root, {"files": {name: expected}})
                    valid.append(name)
                except (RuntimeError, OSError):
                    pass
            if sum(model["files"][n]["size"] for n in valid) > sum(model["files"][n]["size"] for n in best):
                best = valid
        missing = [v["size"] for k, v in model["files"].items() if k not in best]
        ancestor = base
        while not ancestor.exists():
            ancestor = ancestor.parent
        stat = ancestor.stat(); fs = os.statvfs(ancestor)
        needed = sum(missing)
        if needed and not os.access(ancestor, os.W_OK):
            raise RuntimeError("cache_not_writable:" + alias)
        records.append({"alias": alias, "cache": str(base),
                        "filesystem": str(stat.st_dev) + ":" + str(fs.f_fsid),
                        "free_bytes": shutil.disk_usage(ancestor).free,
                        "missing_bytes": needed, "largest_missing_file": max(missing, default=0),
                        "verified_files": len(best), "catalog_files": len(model["files"])})
    return records


def resolve(alias, cache=None, offline=True):
    model = catalog()[alias]
    if model["hub"] == "huggingface":
        from huggingface_hub import snapshot_download
        path = snapshot_download(repo_id=model["repo_id"], revision=model["revision"],
                                 cache_dir=cache, local_files_only=offline,
                                 allow_patterns=list(model["files"]))
    else:
        # A populated SDK cache is usable only when its exact files verify.
        cached = Path(cache or os.getenv("MODELSCOPE_CACHE", "/models")) / "models" / model["repo_id"]
        if alias in {"fsmn", "cam"} and cached.is_dir():
            return verify(cached, model)
        from modelscope import snapshot_download
        path = snapshot_download(model["repo_id"], revision=model["revision"],
                                 cache_dir=cache, local_files_only=offline,
                                 allow_patterns=list(model["files"]))
    return verify(path, model)


def verify_identity(path, repo_id, revision):
    matches = [m for m in catalog().values() if m["repo_id"] == repo_id and m["revision"] == revision]
    if len(matches) != 1:
        raise RuntimeError("model_identity_not_in_catalog")
    return verify(path, matches[0])


def main(argv=None):
    p = argparse.ArgumentParser(description="Prepare or verify catalog models; no server token required")
    p.add_argument("action", choices=["list", "prepare", "verify", "plan"])
    p.add_argument("models", nargs="*", choices=sorted(catalog()))
    p.add_argument("--cache", help="SDK cache directory; defaults to the selected role's environment")
    a = p.parse_args(argv)
    try:
        if a.action == "list":
            value = catalog()
        elif a.action == "plan":
            value = storage_plan(a.models, a.cache)
        else:
            if not a.models:
                p.error("select at least one model alias")
            value = {alias: {"path": resolve(alias, a.cache, offline=a.action == "verify"),
                             "verified": True} for alias in a.models}
        print(json.dumps(value, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "detail": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
