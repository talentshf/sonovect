"""DashScope file-transcription protocol over the native durable task store."""
import hashlib
import hmac
import stat
import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .backends import build_backend
from .models import Options
from .remote_input import input_url
from .media import MediaError
from .store import encoded


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    file_urls: list[Annotated[str, Field(min_length=1, max_length=16384)]] = Field(min_length=1, max_length=1)


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    language_hints: list[Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[\w-]+$")]] = Field(default_factory=list, max_length=1)
    diarization_enabled: bool = False
    vocabulary: dict[Annotated[str, Field(min_length=1, max_length=80)], Annotated[int, Field(ge=1, le=5)]] = Field(default_factory=dict, max_length=200)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=200)
    input: Input
    parameters: Parameters = Field(default_factory=Parameters)


class SubtaskResult(BaseModel):
    subtask_status: Literal["SUCCEEDED", "FAILED"]
    transcription_url: str | None = None
    code: str | None = None


class TaskOutput(BaseModel):
    task_id: str
    task_status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"]
    results: list[SubtaskResult] | None = None
    task_metrics: dict[str, int] | None = None


class TaskReceipt(BaseModel):
    request_id: str
    output: TaskOutput


class Word(BaseModel):
    text: str
    begin_time: int
    end_time: int


class Sentence(BaseModel):
    sentence_id: int
    text: str
    begin_time: int | None = None
    end_time: int | None = None
    speaker_id: int | None = None
    words: list[Word] | None = None


class ChannelTranscript(BaseModel):
    channel_id: int
    text: str
    sentences: list[Sentence]


class ResultFile(BaseModel):
    transcripts: list[ChannelTranscript]


def signing_key(settings):
    p = settings.compat_signing_key_file
    if p is None or p.is_symlink() or not p.is_file():
        raise ValueError("compatible_signing_key_unavailable")
    info = p.stat()
    if stat.S_IMODE(info.st_mode) & 0o077 or not 32 <= info.st_size <= 4096:
        raise ValueError("compatible_signing_key_permissions_or_size")
    key = p.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ValueError("compatible_signing_key_too_short")
    return key


def sign(key, job_id, checksum, expires):
    return hmac.new(key, f"{job_id}:{checksum}:{expires}".encode(), hashlib.sha256).hexdigest()


def install(app, settings, store, authenticate):
    # The disabled routes still appear in the generated contract. Opt-in is an
    # operator decision; no native task, model or token is changed by default.
    key = signing_key(settings) if settings.compat_model else None
    app.state.engine_identity = lambda: build_backend(settings).identity()
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    def enabled():
        if not settings.compat_model:
            raise HTTPException(503, "compatible_service_not_configured")

    @router.get("/models")
    def models():
        enabled()
        try:
            identity = app.state.engine_identity()
        except Exception:
            raise HTTPException(503, "engine_identity_unavailable") from None
        return {"object": "list", "data": [{"id": settings.compat_model, "object": "model",
                "owned_by": "sonovect", "capabilities": {"sentence_timestamps": True,
                    "word_timestamps": bool(identity.get("forced_aligner")),
                    "speaker_diarization": bool(identity.get("speaker_diarization")),
                    "hotwords": {"mode": "inline", "effect": "model-dependent-hint"}},
                "limits": {"max_files": 1, "max_upload_bytes": settings.max_upload_bytes,
                           "max_media_seconds": int(settings.source_seconds_limit)}}]}

    @router.post("/services/audio/asr/transcription", status_code=202, response_model=TaskReceipt,
                 response_model_exclude_none=True)
    def submit(body: Submission,
               x_dashscope_async: Annotated[str | None, Header()] = None,
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
               x_input_sha256: Annotated[str | None, Header(pattern=r"^[0-9a-f]{64}$")] = None):
        enabled()
        if x_dashscope_async != "enable":
            raise HTTPException(400, "async_header_required")
        if body.model != settings.compat_model:
            raise HTTPException(400, "model_not_available")
        try:
            input_url(body.input.file_urls[0], settings.compat_input_hosts)
        except MediaError:
            raise HTTPException(400, "input_url_not_allowed") from None
        try:
            identity = app.state.engine_identity()
            if not isinstance(identity.get("asr"), dict) or not identity["asr"].get("revision"):
                raise ValueError()
        except Exception:
            raise HTTPException(503, "engine_identity_unavailable") from None
        p = body.parameters
        terms = sorted(p.vocabulary, key=lambda v: (-p.vocabulary[v], v))
        options = Options(language=p.language_hints[0] if p.language_hints else None,
                          speakers=p.diarization_enabled, hotwords=terms).wire()
        job_id, created = store.admit_remote(body.input.file_urls[0], options,
            {"model": body.model, "identity": identity, "vocabulary": p.vocabulary}, idempotency_key, x_input_sha256)
        job = store.get(job_id)
        return JSONResponse(task(job), status_code=202 if created else 200)

    def task(job):
        state = job["state"]
        output = {"task_id": job["id"], "task_status": {
            "queued": "PENDING", "running": "RUNNING", "succeeded": "SUCCEEDED",
            "partial": "SUCCEEDED", "failed": "FAILED", "cancelled": "CANCELED"}.get(state, "UNKNOWN")}
        if state == "expired":
            raise HTTPException(410, "result_expired")
        if state in {"succeeded", "partial"} and job["evidence"]:
            data = encoded(job["evidence"][0])
            checksum = hashlib.sha256(data).hexdigest()
            expires = min(int(time.time()) + settings.compat_link_seconds, int(job["expires"]))
            signature = sign(key, job["id"], checksum, expires)
            link = (settings.compat_public_url.rstrip("/") + f"/filetrans-results/{job['id']}"
                    + f"?expires={expires}&sha256={checksum}&signature={signature}")
            output["results"] = [{"subtask_status": "SUCCEEDED", "transcription_url": link}]
            output["task_metrics"] = {"TOTAL": 1, "SUCCEEDED": 1, "FAILED": 0}
        elif state == "failed":
            output["results"] = [{"subtask_status": "FAILED", "code": job["error"] or "processing_failed"}]
        return {"request_id": uuid.uuid4().hex, "output": output}

    @router.get("/tasks/{job_id}", response_model=TaskReceipt, response_model_exclude_none=True)
    def status(job_id: str):
        enabled(); store.prune()
        job = store.get(job_id)
        if not job["protocol"]:
            raise HTTPException(404, "task_not_found")
        return task(job)

    @app.get("/filetrans-results/{job_id}", response_model=ResultFile, response_model_exclude_none=True)
    def result(job_id: str, request: Request, expires: int, sha256: str, signature: str):
        enabled()
        if (len(request.query_params.multi_items()) != 3 or expires <= time.time()
                or not hmac.compare_digest(signature, sign(key, job_id, sha256, expires))):
            raise HTTPException(403, "result_signature_invalid_or_expired")
        store.prune(); job = store.get(job_id)
        if not job["protocol"] or job["state"] not in {"succeeded", "partial"} or not job["evidence"]:
            raise HTTPException(410, "result_unavailable_or_expired")
        data = encoded(job["evidence"][0])
        if expires > job["expires"] or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), sha256):
            raise HTTPException(403, "result_signature_invalid_or_expired")
        return Response(data, media_type="application/json", headers={"Cache-Control": "private, no-store"})

    app.include_router(router)
