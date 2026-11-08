"""Bounded live PCM sessions, separate from the recoverable file-job queue."""
import asyncio
import hmac
import json
import uuid
from typing import Annotated, Literal

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["start"]
    sample_rate: Literal[16000] = 16000
    encoding: Literal["pcm_s16le"] = "pcm_s16le"
    language: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w-]+$")
    hotwords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=200)


class QwenStreamingEngine:
    """Use upstream's stateful streaming API and prefix rollback policy.

    Upstream re-feeds accumulated audio. This is incremental input/output, not
    an assertion of constant-cost online encoding or incremental KV caching.

    qwen-asr 0.0.6 requires its SDK-format weights and Transformers 4.57.6.
    Keep this optional runtime in its own GPU process/environment. It cannot
    replace the existing Transformers 5 file worker or use its -hf checkpoint.
    """
    def __init__(self, settings):
        self.settings, self.model = settings, None

    def start(self, options):
        if self.model is None:
            from qwen_asr import Qwen3ASRModel
            self.model = Qwen3ASRModel.LLM(
                model=self.settings.realtime_model_path,
                max_new_tokens=256, gpu_memory_utilization=self.settings.realtime_gpu_memory_utilization,
                max_model_len=16384, max_num_seqs=1, enforce_eager=True,
            )
        return self.model.init_streaming_state(context=", ".join(options.hotwords), language=options.language,
                                                chunk_size_sec=2.0)

    def push(self, state, pcm):
        import numpy as np
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self.model.streaming_transcribe(audio, state)
        return state.text

    def finish(self, state):
        self.model.finish_streaming_transcribe(state)
        return state.text


def capability(settings):
    vibevoice = settings.realtime_backend == "vibevoice-1.5b"
    return {"enabled": settings.realtime_enabled, "path": "/v1/realtime",
            "protocol": "sonovect.realtime/v1", "model_family": "vibevoice-streaming-1.5b" if vibevoice else "qwen3-asr",
            "sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1,
            "max_frame_bytes": 64000, "max_seconds": settings.realtime_max_seconds,
            "idle_seconds": settings.realtime_idle_seconds, "max_sessions_per_process": 1,
            "partial_semantics": "replace-full-text", "timestamps": False, "speakers": vibevoice,
            "retention": "client-owned", "resume": False, "automatic_retry": False}


def install(app, settings, engine=None):
    gate = asyncio.Lock()
    if engine is None and settings.realtime_backend == "vibevoice-1.5b":
        from .vibevoice_stream import VibeVoiceStreamingEngine
        engine = VibeVoiceStreamingEngine(settings)
    app.state.realtime_engine = engine or QwenStreamingEngine(settings)

    @app.websocket("/v1/realtime")
    async def realtime(ws: WebSocket):
        # Reject before accepting or receiving media. Never put a service token
        # into URLs; browsers need a future scoped ticket flow, not query auth.
        headers = ws.headers.getlist("authorization")
        expected = "Bearer " + settings.token
        if len(headers) != 1 or not hmac.compare_digest(headers[0].encode(), expected.encode()):
            await ws.close(code=1008)
            return
        if not settings.realtime_enabled:
            await ws.close(code=1008, reason="realtime_not_configured")
            return
        await ws.accept()
        if gate.locked():
            await ws.send_json({"type": "error", "code": "realtime_busy"})
            await ws.close(code=1013)
            return
        await gate.acquire()
        task = None
        session_id, seq, size = uuid.uuid4().hex, 0, 0

        async def run(fn, *args):
            nonlocal task
            task = asyncio.create_task(asyncio.to_thread(fn, *args))
            # Cancellation/disconnect must not free the GPU slot while its
            # synchronous model call is still running in a background thread.
            return await asyncio.shield(task)

        async def event(kind, text=None, **extra):
            nonlocal seq
            seq += 1
            value = {"type": kind, "session_id": session_id, "sequence": seq,
                     "received_audio_ms": size // 32, **extra}
            if text is not None:
                from .vibevoice_stream import LiveText
                if isinstance(text, LiveText):
                    value["speaker_segments"] = text.speaker_segments
                    text = text.text
                if not isinstance(text, str) or len(text) > 200000:
                    raise ValueError("invalid_engine_text")
                value["text"] = text
            await ws.send_json(value)

        engine = app.state.realtime_engine
        try:
            first = await asyncio.wait_for(ws.receive(), settings.realtime_idle_seconds)
            if first["type"] == "websocket.disconnect":
                return
            raw = first.get("text")
            if not isinstance(raw, str):
                raise ValueError("invalid_start")
            if len(raw.encode()) > 20000:
                raise ValueError("invalid_start")
            options = Start.model_validate_json(raw)
            state = await asyncio.wait_for(run(engine.start, options), settings.realtime_max_seconds + settings.realtime_idle_seconds)
            await event("started", capabilities=capability(settings))
            async with asyncio.timeout(settings.realtime_max_seconds + settings.realtime_idle_seconds):
                while True:
                    msg = await asyncio.wait_for(ws.receive(), settings.realtime_idle_seconds)
                    if msg["type"] == "websocket.disconnect":
                        break
                    pcm = msg.get("bytes")
                    if pcm is not None:
                        if not pcm or len(pcm) % 2 or len(pcm) > 64000:
                            await event("error", code="invalid_pcm_frame")
                            break
                        if size + len(pcm) > settings.realtime_max_seconds * 32000:
                            await event("error", code="realtime_duration_limit_exceeded")
                            break
                        size += len(pcm)
                        text = await run(engine.push, state, pcm)
                        await event("partial", text)
                    else:
                        raw = msg.get("text", "")
                        if len(raw) > 100 or json.loads(raw) != {"type": "finish"} or not size:
                            raise ValueError("invalid_control")
                        text = await run(engine.finish, state)
                        await event("final", text)
                        break
        except WebSocketDisconnect:
            pass
        except (TimeoutError, ValueError, TypeError, ValidationError, RuntimeError, ImportError) as exc:
            code = "realtime_timeout" if isinstance(exc, TimeoutError) else "realtime_invalid_request" if isinstance(exc, (ValueError, TypeError, ValidationError)) else "realtime_engine_unavailable"
            try:
                await event("error", code=code)
            except (RuntimeError, WebSocketDisconnect):
                pass
        except Exception:
            try:
                await event("error", code="realtime_engine_failed")
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            if task is not None and not task.done():
                def release(done):
                    if not done.cancelled():
                        done.exception()
                    gate.release()
                task.add_done_callback(release)
            else:
                gate.release()
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass


def create_realtime_app(settings=None):
    """Optional GPU-only serving process. No file queue or worker is created."""
    from fastapi import FastAPI
    from .config import Settings
    settings = settings or Settings.from_env()
    if not settings.realtime_enabled:
        raise ValueError("enable_realtime_explicitly")
    app = FastAPI(title="Sonovect realtime", docs_url=None, redoc_url=None)
    install(app, settings)
    from .limits import BearerGate
    from . import __version__
    app.add_middleware(BearerGate, token=settings.token)

    @app.get("/v1/capabilities")
    def realtime_capabilities():
        return {"version": __version__, "api_version": "v1", "realtime": capability(settings),
                "execution": {"mode": "realtime-sessions", "streaming": True}}

    @app.get("/health")
    def health():
        # Liveness only: this does not claim model loading or inference passed.
        return {"status": "ok", "model_loaded": app.state.realtime_engine.model is not None}
    return app
