"""Bounded source-tree hygiene scan. Never prints matching secret values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "absolute-user-home": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "appliance-volume": re.compile(r"/vol\d+/\d+/"),
    "private-network-address": re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE" + r" KEY-----"),
    "provider-credential": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b"),
}


def scan_text(relative, content):
    findings = []
    for name, rule in RULES.items():
        checked = content
        if name == "private-network-address" and relative.endswith("requirements.lock"):
            # CUDA packages have four-part versions (e.g. curand). Those are
            # package metadata, not endpoint addresses. URLs/comments still scan.
            checked = re.sub(r"(?m)^([A-Za-z0-9_.-]+)==[0-9][0-9A-Za-z.+-]*$",
                             r"\1==<package-version>", content)
        if rule.search(checked):
            findings.append(name)
    return findings


def check():
    listing = subprocess.check_output(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=ROOT)
    failures, count = [], 0
    for relative in sorted(set(listing.decode().split("\0"))):
        if not relative:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        count += 1
        if path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".aiff", ".aac", ".ogg", ".opus", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".sqlite3", ".bin", ".safetensors", ".pt", ".pth", ".pyc"}:
            failures.append((relative, "runtime-or-model-binary"))
            continue
        if path.is_symlink():
            failures.append((relative, "symbolic-link"))
            continue
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            failures.append((relative, "unexpected-binary"))
            continue
        failures.extend((relative, name) for name in scan_text(relative, content))
    for relative, rule in failures:
        print(f"{relative}: {rule}", file=sys.stderr)
    print(f"Checked {count} source files; {len(failures)} hygiene findings")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(check())
