"""Versioned HTTP API. Start with uvicorn's application factory."""
import hashlib
import hmac
import json
import os
import tempfile
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings
from .capabilities import describe
from .models import Options, Transcript, Analysis
from .limits import BodyLimit, BearerGate
from .results import as_srt, as_text
from .store import Conflict, Store, encoded


def create_app(settings=None):
    settings = settings or Settings.from_env()
    store = Store(settings)
    app = FastAPI(title="Sonovect", version=__version__,
                  description="Self-hosted ASR for audio and video soundtracks, FunASR speech results and separate sound analysis.")
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(BodyLimit, maximum=settings.max_upload_bytes + settings.max_files * 8192 + 20000)

    # Last added user middleware runs first: reject before body limits or parsing.
    app.add_middleware(BearerGate, token=settings.token)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        code = error.detail if isinstance(error.detail, str) else "request_failed"
        return problem(request, error.status_code, code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return problem(request, 422, "invalid_request")

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return problem(request, 404, "job_not_found")

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return problem(request, 409, str(error))

    bearer = HTTPBearer(auto_error=False)
    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), settings.token.encode()):
            raise HTTPException(401, "authentication_required", headers={"WWW-Authenticate": "Bearer"})

    router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    def ready():
        try:
            with store.connect() as con:
                con.execute("SELECT 1").fetchone()
            workers = store.available_workers(__version__)
            if not workers:
                raise ValueError("worker_unavailable")
            if settings.backend == "speech":
                with httpx.Client(timeout=5, trust_env=False) as client:
                    response = client.get(settings.provider_url + "/health")
                    response.raise_for_status()
                    discovery = response.json()
                    if discovery.get("status") not in {"ok", "ready", "healthy"}:
                        raise ValueError("provider_unready")
                    if "sound_analysis" in discovery and discovery["sound_analysis"] != settings.sound_enabled:
                        raise ValueError("provider_capability_configuration_mismatch")
                    if discovery.get("voice_analysis", False) != settings.voice_enabled:
                        raise ValueError("provider_voice_configuration_mismatch")
                    if discovery.get("voice_measurements", False) != settings.measurements_enabled:
                        raise ValueError("provider_measurements_configuration_mismatch")
                    if settings.voice_enabled and discovery.get("voice_backend", "moss") != settings.voice_backend:
                        raise ValueError("provider_voice_backend_mismatch")
            return {"status": "ready", "scope": "queue-worker-and-backend-discovery", "available_workers": workers, "model_inference_verified": False}
        except Exception:
            return JSONResponse({"status": "not_ready", "scope": "queue-worker-and-backend-discovery"}, status_code=503)

    @router.get("/capabilities")
    def capabilities():
        result = describe(settings)
        if settings.backend == "speech":
            try:
                with httpx.Client(timeout=5, trust_env=False) as client:
                    response = client.get(settings.provider_url + "/models")
                    response.raise_for_status()
                    result["models"] = response.json()
            except Exception:
                result["models"] = {"discovery_available": False}
        else:
            result["models"] = {"asr": settings.model, "revision": settings.model_revision}
        return result

    @router.post("/jobs", status_code=202)
    async def submit(files: Annotated[list[UploadFile], File()],
                     options: Annotated[str, Form(max_length=20000)] = "{}",
                     idempotency_key: Annotated[str | None, Header(max_length=128, min_length=1)] = None):
        if not 1 <= len(files) <= settings.max_files:
            raise HTTPException(422, "invalid_file_count")
        try:
            selected = Options.model_validate_json(options)
        except (ValidationError, ValueError):
            raise HTTPException(422, "invalid_options")
        if selected.analyze_sound and not describe(settings)["sound_analysis"]:
            raise HTTPException(422, "sound_backend_not_configured")
        if selected.analyze_voice and not describe(settings)["voice_analysis"]:
            raise HTTPException(422, "voice_backend_not_configured")
        from .models import measurements_requested
        if measurements_requested(selected.wire()) and not describe(settings)["voice_measurements"]:
            raise HTTPException(422, "measurements_backend_not_configured")
        sources, total = [], 0
        # Temporary uploads live on the same operator-selected volume as the queue.
        with tempfile.TemporaryDirectory(prefix="upload-", dir=store.root) as directory:
            for i, upload in enumerate(files):
                path = store.root / directory / f"{i}.audio"
                digest, size = hashlib.sha256(), 0
                with path.open("wb") as target:
                    os.chmod(path, 0o600)
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if total > settings.max_upload_bytes:
                            raise HTTPException(413, "upload_limit_exceeded")
                        digest.update(chunk)
                        target.write(chunk)
                if not size:
                    raise HTTPException(422, "empty_audio")
                sources.append({"path": str(path), "sha256": digest.hexdigest(), "size": size})
            job_id, created = store.admit(sources, selected.wire(), idempotency_key)
        return JSONResponse(store.public(job_id), status_code=202 if created else 200,
                            headers={"Location": f"/v1/jobs/{job_id}"})

    @router.get("/jobs/{job_id}")
    def status(job_id: str):
        store.prune()
        return store.public(job_id)

    def completed(job_id):
        store.prune()
        job = store.get(job_id)
        if job["state"] == "expired":
            raise HTTPException(410, "result_expired")
        if job["state"] not in {"succeeded", "partial"}:
            raise HTTPException(409, "result_unavailable")
        return job

    @router.get("/jobs/{job_id}/result", response_model=list[Transcript], response_model_exclude_none=True,
                responses={200: {"content": {"text/plain": {}, "application/x-subrip": {}}}})
    def result(job_id: str, format: Literal["json", "text", "srt"] = "json"):
        values = completed(job_id)["result"]
        if format == "json":
            return Response(encoded(values), media_type="application/json")
        if format == "text":
            return Response(as_text(values), media_type="text/plain; charset=utf-8")
        try:
            return Response(as_srt(values), media_type="application/x-subrip")
        except ValueError:
            raise HTTPException(422, "subtitle_timing_unavailable_or_multiple_sources")

    @router.get("/jobs/{job_id}/analysis", response_model=list[Analysis], response_model_exclude_none=True)
    def analysis(job_id: str):
        return Response(encoded(completed(job_id)["analysis"]), media_type="application/json")

    @router.get("/jobs/{job_id}/manifest")
    def manifest(job_id: str):
        job = completed(job_id)
        artifacts = []
        for layer, value in (("result", job["result"]), ("analysis", job["analysis"])):
            content = encoded(value)
            artifacts.append({"name": f"{layer}.json", "url": f"/v1/jobs/{job_id}/{layer}",
                              "sha256": hashlib.sha256(content).hexdigest(), "size": len(content), "media_type": "application/json"})
        return {"job_id": job_id, "attempt": job["attempt"], "artifacts": artifacts}

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return store.cancel(job_id)

    @router.post("/jobs/{job_id}/retry", status_code=202)
    def retry(job_id: str):
        return store.retry(job_id)

    app.include_router(router)
    return app


def problem(request: Request, status: int, code: str):
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse({"type": f"urn:sonovect:error:{code}", "title": code,
                         "status": status, "code": code, "instance": request.url.path},
                        status_code=status, media_type="application/problem+json", headers=headers)
