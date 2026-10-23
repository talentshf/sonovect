"""Bounded container probes; a healthy process is not an accuracy claim."""
import argparse
import json
import os
from pathlib import Path
import urllib.request
from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["api", "worker"])
    args = parser.parse_args(argv)
    try:
        if args.role == "api":
            with urllib.request.urlopen("http://127.0.0.1:8096/ready", timeout=5) as response:
                ok = json.load(response).get("status") == "ready"
        else:
            from .config import Settings
            from .store import Store
            owner = json.loads(Path(os.getenv("SONOVECT_WORKER_HEALTH_FILE", "/tmp/sonovect-worker.json")).read_text())["owner"]
            ok = bool(owner) and Store(Settings.from_env()).available_workers(__version__, owner) > 0
    except Exception:
        ok = False
    print(json.dumps({"status": "ready" if ok else "not_ready", "role": args.role}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
