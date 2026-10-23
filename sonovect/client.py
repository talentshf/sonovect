"""Shared HTTP client for CLI and MCP; no host-specific credential lookup."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import math
import os
import time
import httpx
from .models import Options
from .auth import token_from_env
from .store import TERMINAL


class Client:
    def __init__(self, url=None, token=None, transport=None):
        self.url = (url or os.getenv("SONOVECT_URL", "http://127.0.0.1:8096")).rstrip("/")
        token = token or token_from_env()
        if not token:
            raise ValueError("SONOVECT_TOKEN is required")
        self.http = httpx.Client(base_url=self.url, headers={"Authorization": "Bearer " + token},
                                 timeout=300, trust_env=False, transport=transport)

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        if response.is_error:
            # Do not echo response bodies, input data, tokens or server URLs.
            try:
                code = response.json().get("code", "request_failed")
            except ValueError:
                code = "request_failed"
            raise RuntimeError(f"HTTP {response.status_code}: {code}")
        return response

    def submit(self, paths, options=None, idempotency_key=None):
        selected = options or Options()
        if not paths:
            raise ValueError("At least one audio file is required")
        with ExitStack() as stack:
            files = [("files", ("audio.wav", stack.enter_context(Path(path).open("rb")), "application/octet-stream")) for path in paths]
            headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
            return self.request("POST", "/v1/jobs", files=files, data={"options": json.dumps(selected.wire(), separators=(",", ":"))}, headers=headers).json()

    def status(self, job_id):
        return self.request("GET", f"/v1/jobs/{job_id}").json()

    def wait(self, job_id, timeout=7200, poll=2):
        if any(not math.isfinite(v) or v <= 0 for v in (timeout, poll)):
            raise ValueError("Wait timeout and poll must be finite and positive")
        deadline = time.monotonic() + timeout
        # Observe short jobs promptly, then bound traffic for long recordings.
        delay = min(0.1, poll)
        while True:
            value = self.status(job_id)
            if value["status"] in TERMINAL:
                return value
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} is still processing; query the same job ID")
            time.sleep(min(delay, remaining))
            delay = min(poll, delay * 2)

    def export(self, job_id, directory):
        manifest = self.request("GET", f"/v1/jobs/{job_id}/manifest").json()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        for artifact in manifest["artifacts"]:
            name = artifact["name"]
            # Never follow file names or off-origin URLs supplied by a remote endpoint.
            if name not in {"result.json", "analysis.json"}:
                raise ValueError("Invalid artifact name")
            layer = name.removesuffix(".json")
            data = self.request("GET", f"/v1/jobs/{job_id}/{layer}").content
            if len(data) != artifact["size"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise ValueError("Artifact integrity check failed")
            path = directory / name
            with path.open("xb") as target:
                os.chmod(path, 0o600)
                target.write(data)
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        os.chmod(path, 0o600)
        return manifest
