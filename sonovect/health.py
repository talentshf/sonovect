"""Bounded container probes; a healthy process is not an accuracy claim."""
import argparse
import json
import os
from pathlib import Path

from . import __version__
from .config import Settings
from .store import Store, StoreBusy


def worker_report():
    component = "queue.worker"
    try:
        settings = Settings.from_env()
    except Exception:
        return {"status": "not_ready", "role": "worker", "component": "service", "code": "diagnostic_internal_error"}
    try:
        owner = json.loads(Path(os.getenv("SONOVECT_WORKER_HEALTH_FILE", "/tmp/sonovect-worker.json")).read_text())["owner"]
        if not isinstance(owner, str) or not owner:
            raise ValueError("invalid_owner")
    except FileNotFoundError:
        code = "worker_absent"
    except Exception:
        code = "worker_unavailable"
    else:
        try:
            code = Store.worker_snapshot(settings, __version__, owner)["code"]
        except StoreBusy:
            code, component = "database_busy", "queue.database"
        except Exception:
            code, component = "database_unavailable", "queue.database"
    return {"status": "not_ready" if code else "ready", "role": "worker", "component": component, "code": code or "ready"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["api", "worker"])
    args = parser.parse_args(argv)
    if args.role == "worker":
        value = worker_report()
    else:
        from .client import Client
        try:
            with_client = Client(url="http://127.0.0.1:8096")
            try:
                value = with_client.readiness()
            finally:
                with_client.close()
            value["role"] = "api"
        except Exception:
            value = {"status": "not_ready", "role": "api", "component": "service", "code": "diagnostic_internal_error"}
    print(json.dumps(value))
    return 0 if value["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
