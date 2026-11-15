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
                value = response.json()
                code = value.get("code") or (value.get("error") or {}).get("code", "request_failed")
            except ValueError:
                code = "request_failed"
            job_id = response.headers.get("x-sonovect-job-id", "")
            import re
            recovery = f"; job_id={job_id}" if re.fullmatch(r"[a-f0-9]{32}", job_id) else ""
            raise RuntimeError(f"HTTP {response.status_code}: {code}{recovery}")
        return response

    def transcribe(self, path, *, model=None, language=None, prompt="", idempotency_key=None):
        if model is None:
            choices = self.request("GET", "/v1/models").json()["data"]
            choices = [x for x in choices if "transcription" in x.get("sonovect", {}).get("tasks", ["transcription"])]
            if len(choices) != 1:
                raise ValueError("select_transcription_model")
            model = choices[0]["id"]
        fields = {"model": model, "response_format": "json"}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        with Path(path).open("rb") as audio:
            response = self.request("POST", "/v1/audio/transcriptions", data=fields,
                files={"file": ("audio", audio, "application/octet-stream")},
                headers={"Idempotency-Key": idempotency_key} if idempotency_key else {})
        return {"text": response.json()["text"], "job_id": response.headers.get("x-sonovect-job-id")}

    def readiness(self, details=False):
        """Only a validated readiness 503 is a report rather than a request error."""
        from .readiness import CODES, COMPONENTS, SCOPE, Report, Summary
        path = "/v1/diagnostics/readiness" if details else "/ready"
        def read(path):
            with self.http.stream("GET", path, timeout=8, follow_redirects=False) as response:
                status = response.status_code
                if status == 404 and details:
                    return status, None
                if status not in {200, 503}:
                    raise ValueError("invalid_readiness_response")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 32 * 1024:
                        raise ValueError("invalid_readiness_response")
            return status, json.loads(body)
        try:
            status, value = read(path)
            unsupported = details and status == 404
            if unsupported:
                status, value = read("/ready")
            if status not in {200, 503}:
                raise ValueError("invalid_readiness_response")
            expected = "ready" if status == 200 else "not_ready"
            if not isinstance(value, dict) or value.get("scope") != SCOPE or value.get("status") != expected:
                raise ValueError("invalid_readiness_response")
            # Older servers had no code, component or failure worker count.
            value.setdefault("code", "ready" if expected == "ready" else "service_not_ready")
            value.setdefault("component", "service")
            value.setdefault("available_workers", None)
            value.setdefault("model_inference_verified", False)
            if value["code"] not in CODES or value["component"] not in COMPONENTS:
                raise ValueError("invalid_readiness_response")
            if details and not unsupported:
                value = Report.model_validate(value).model_dump(by_alias=True)
                for row in value["checks"] + value["errors"] + value["warnings"]:
                    if row["component"] not in COMPONENTS or (row.get("code") and row["code"] not in CODES):
                        raise ValueError("invalid_readiness_response")
                for row in value["checks"]:
                    if row.get("action") not in {None, "check_container_gpu_access", "check_worker_presence", "check_queue_storage"}:
                        raise ValueError("invalid_readiness_response")
            else:
                value = Summary.model_validate(value).model_dump()
            if unsupported:
                value["details_supported"] = False
            return value
        except httpx.HTTPError:
            raise RuntimeError("readiness_request_failed") from None
        except (ValueError, TypeError, KeyError):
            raise RuntimeError("invalid_readiness_response") from None

    def submit(self, paths, options=None, idempotency_key=None, callback_url=None):
        selected = options or Options()
        if not paths:
            raise ValueError("At least one audio file is required")
        with ExitStack() as stack:
            files = [("files", ("audio.wav", stack.enter_context(Path(path).open("rb")), "application/octet-stream")) for path in paths]
            headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
            fields = {"options": json.dumps(selected.wire(), separators=(",", ":"))}
            if callback_url:
                fields["callback_url"] = callback_url
            return self.request("POST", "/v1/jobs", files=files, data=fields, headers=headers).json()

    def status(self, job_id):
        return self.request("GET", f"/v1/jobs/{job_id}").json()

    def wait(self, job_id, timeout=7200):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Wait timeout must be finite and positive")
        deadline = time.monotonic() + timeout
        value = self.status(job_id)
        if value["status"] in TERMINAL:
            return value
        try:
            with self.http.stream("GET", f"/v1/jobs/{job_id}/events", headers={"Accept":"text/event-stream"},
                                  timeout=httpx.Timeout(timeout,read=min(20,timeout))) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"wait_unavailable; job_id={job_id}")
                for line in response.iter_lines():
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Job {job_id} is still processing; query the same job ID")
                    if line.startswith("event: ") and line[7:] in {"job.succeeded","job.partial","job.failed","job.cancelled","job.expired"}:
                        return self.status(job_id)
                    if line.startswith("data: "):
                        if len(line)>131072:continue
                        event=json.loads(line[6:])
                        if event.get("type") in {"job.succeeded","job.partial","job.failed","job.cancelled","job.expired"}:
                            return self.status(job_id)
        except httpx.TimeoutException:
            raise TimeoutError(f"Job {job_id} is still processing; query the same job ID") from None
        except httpx.HTTPError:
            raise RuntimeError(f"wait_connection_failed; job_id={job_id}") from None
        value=self.status(job_id)
        if value["status"] in TERMINAL:return value
        raise RuntimeError(f"wait_interrupted; job_id={job_id}")

    def export(self, job_id, directory):
        manifest = self.request("GET", f"/v1/jobs/{job_id}/manifest").json()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        for artifact in manifest["artifacts"]:
            name = artifact["name"]
            # Never follow file names or off-origin URLs supplied by a remote endpoint.
            if name not in {"result.json", "analysis.json", "translation.json"}:
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
