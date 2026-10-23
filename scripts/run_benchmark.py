"""Replay a frozen corpus through the public API, retaining failures and receipts.

Audio and reference manifests stay outside the source tree. References are never
sent to inference. Run the offline evaluator separately after inference finishes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def verify_export(directory):
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for item in manifest["artifacts"]:
        if item["name"] not in {"result.json", "analysis.json"}:
            raise ValueError("Invalid artifact name")
        path = directory / item["name"]
        if path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
            raise ValueError("Artifact integrity mismatch")


def export_atomic(client, job_id, directory):
    partial = directory.with_name(".partial-" + directory.name)
    if not directory.exists() and partial.exists():
        allowed = {"result.json", "analysis.json", "manifest.json"}
        if partial.is_symlink() or not partial.is_dir() or any(
            p.name not in allowed or p.is_symlink() or not p.is_file() for p in partial.iterdir()
        ):
            raise ValueError("Unexpected contents in partial export; preserved for inspection")
        try:
            verify_export(partial)
        except (FileNotFoundError, json.JSONDecodeError):
            # Only this run's unpublished download is disposable. A digest
            # mismatch is deliberately not caught or silently repaired.
            shutil.rmtree(partial)
        else:
            partial.rename(directory)
    if not directory.exists():
        client.export(job_id, partial)
        verify_export(partial)
        partial.rename(directory)
    verify_export(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--groups", help="Comma-separated exact corpus groups; omitted means every case")
    parser.add_argument("--timeout", type=float, default=7200)
    args = parser.parse_args(argv)
    from sonovect.client import Client
    from sonovect.models import Options

    if digest(args.dataset) != args.dataset_sha256:
        raise ValueError("Frozen dataset digest mismatch")
    dataset = json.loads(args.dataset.read_bytes())
    cases = dataset["cases"]
    if args.groups:
        groups = set(args.groups.split(","))
        if not groups <= {c["group"] for c in cases}:
            raise ValueError("Unknown corpus group")
        cases = [c for c in cases if c["group"] in groups]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Empty corpus or duplicate case IDs")
    if any(not isinstance(c["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", c["id"]) for c in cases):
        raise ValueError("Case IDs must be safe file names, at most 128 characters")
    # Check every input before submitting any job. Never silently replace a case.
    for case in cases:
        if digest(Path(case["audio_path"])) != case["sha256"]:
            raise ValueError("Audio digest mismatch: " + case["id"])
    if args.output.exists() and any(args.output.iterdir()) and not (args.output / "jobs.json").is_file():
        raise ValueError("Existing nonempty output directory has no run receipt; preserved")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    binding = {"run_id": args.run_id, "dataset_sha256": args.dataset_sha256,
               "version": args.version, "case_ids": [c["id"] for c in cases]}
    receipt_path = args.output / "jobs.json"
    if receipt_path.exists():
        receipts = json.loads(receipt_path.read_bytes())
        if receipts["binding"] != binding:
            raise ValueError("Existing run has a different binding")
    else:
        receipts = {"binding": binding, "started_utc": datetime.now(timezone.utc).isoformat(), "jobs": {}}
        save(receipt_path, receipts)
    # The filtered reference file is only for the offline scorer; original digest
    # and exact selected IDs remain bound above, including for a resumed run.
    save(args.output / "references.json", {**dataset, "cases": cases,
                                          "parent_dataset_sha256": args.dataset_sha256})
    client = Client()
    try:
        health = client.request("GET", "/health").json()
        if health.get("version") != args.version:
            raise ValueError("Service version mismatch")
        predictions = []
        for case in cases:
            receipt = receipts["jobs"].get(case["id"])
            if receipt is None:
                started = time.time()
                job = client.submit([case["audio_path"]], Options(
                    language=None if case["language"] in {"none", "auto"} else case["language"],
                    speakers=True, analyze_sound=case.get("analyze_sound", False),
                    analyze_voice=case.get("analyze_voice", False)),
                    idempotency_key=args.run_id + ":" + case["id"])
                receipt = {"job_id": job["id"], "submitted_unix": started}
                receipts["jobs"][case["id"]] = receipt
                save(receipt_path, receipts)
            job = client.wait(receipt["job_id"], timeout=args.timeout, poll=1)
            if "finished_unix" not in receipt:
                receipt["finished_unix"] = time.time()
                receipt["elapsed_seconds"] = receipt["finished_unix"] - receipt["submitted_unix"]
            receipt["status"] = job
            prediction = {"id": case["id"], "status": job["sources"][0]["status"], "job_id": job["id"]}
            if job["status"] in {"succeeded", "partial"}:
                directory = args.output / "artifacts" / case["id"]
                export_atomic(client, job["id"], directory)
                for layer, name in (("result", "transcript"), ("analysis", "analysis")):
                    values = json.loads((directory / (layer + ".json")).read_bytes())
                    prediction[name] = next((v for v in values if v["key"] == "audio_0000"), None)
            predictions.append(prediction)
            save(receipt_path, receipts)
            save(args.output / "predictions.json", {"binding": binding, "cases": predictions})
            print(json.dumps({"finished": case["id"], "status": prediction["status"],
                              "analysis_status": (prediction.get("analysis") or {}).get("status"),
                              "elapsed_seconds": round(receipt["elapsed_seconds"], 3),
                              "completed": len(predictions), "total": len(cases)}), flush=True)
        receipts.setdefault("finished_utc", datetime.now(timezone.utc).isoformat())
        save(receipt_path, receipts)
    finally:
        client.close()


if __name__ == "__main__":
    main()
