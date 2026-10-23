from __future__ import annotations

from gpu_health import gpu_health
from fastapi.responses import JSONResponse

import asyncio
import gc
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import librosa
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from huggingface_hub import snapshot_download
from transformers import Qwen2Tokenizer
from src.modeling_moss_audio import MossAudioModel
from src.processing_moss_audio import MossAudioProcessor
from failure_cleanup import detach_exception
from snapshot_cache import resolve_pinned_snapshot
from gpu_capacity import wait_for_capacity
from gpu_stage import GPUStage
from gpu_release import allocator_state, release_idle_cuda, IDLE_RESERVED_MIB
from vocal_output import audible_description
from typing_extensions import Annotated


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("moss-audio-worker")

from sonovect_version import VERSION as APP_VERSION
from runtime_config import validate_environment
validate_environment()
MODEL_ID = os.getenv("MOSS_AUDIO_MODEL", "OpenMOSS-Team/MOSS-Audio-4B-Instruct")
MODEL_REVISION = os.getenv("MOSS_AUDIO_REVISION", "6907a499dc0e87cc77c8ae0fe23fd0eb5476a02d")
DEVICE = os.getenv("MOSS_DEVICE", "cuda:0")
MAX_CHUNK_SECONDS = int(os.getenv("MOSS_MAX_CHUNK_SECONDS", "90"))
MAX_NEW_TOKENS = int(os.getenv("MOSS_MAX_NEW_TOKENS", "768"))
STRUCTURED_RETRIES = max(0, int(os.getenv("MOSS_STRUCTURED_RETRIES", "2")))
UNLOAD_AFTER_REQUEST = os.getenv("MOSS_UNLOAD_AFTER_REQUEST", "true").lower() == "true"
IDLE_UNLOAD_SECONDS = int(os.getenv("MOSS_IDLE_UNLOAD_SECONDS", "300"))
if IDLE_UNLOAD_SECONDS <= 0:
    raise RuntimeError("moss_idle_timeout_must_be_positive")
DEBUG_RAW = os.getenv("MOSS_DEBUG_RAW", "false").lower() == "true"
MIN_FREE_GPU_BYTES = int(float(os.getenv("MOSS_MIN_FREE_GIB", "10")) * 1024**3)

EMOTIONS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED", "SORRY"}


def _require_gpu_capacity() -> None:
    if not DEVICE.startswith("cuda"):
        return
    wait_for_capacity(
        lambda: torch.cuda.mem_get_info(DEVICE), max(MIN_FREE_GPU_BYTES,
            (int(os.getenv("MOSS_GPU_BUDGET_MIB", "12288")) + int(os.getenv("GPU_RESERVE_MIB", "1024"))) * 1024**2),
        timeout=float(os.getenv("GPU_CAPACITY_WAIT_SECONDS", "360")),
        on_wait=lambda waiting: setattr(manager, "_waiting_for_gpu", waiting),
    )

PROMPT = """First determine whether any human speaking, singing, laughing, crying or other human vocalization is audible. The input may contain only environmental sounds, music, noise or tones. Do not assume that a speaker exists.
Return exactly one compact JSON object with three keys: vocal_present, emotions and voice.
vocal_present must be true, false, or null when uncertain. If no human vocalization is audible or uncertain, return emotions: [] and voice: {}. Do not invent a voice to fill the fields.
Only when vocal_present is true, identify the predominant emotional tone from audible prosody, not from the meaning of the words.
Choose one label: NEUTRAL (ordinary or unemotional), ANGRY (angry or irritated), DISGUSTED (disgust or aversion), FEARFUL (fear or anxiety), HAPPY (happiness or excitement), SAD (sadness), SORRY (apologetic), SURPRISED (surprise).
When vocal_present is true, emotions must be a list containing one object with a label key. Use NEUTRAL for an audible voice without a salient emotion.
voice must be an object with confident string descriptions of accent, pitch, volume, speed, texture, clarity, fluency and tone. Omit uncertain fields; {} is valid.
Do not classify or describe environmental sounds, music or other sound events. Do not transcribe words, infer identity, age, gender, personality or medical conditions. Do not produce timestamps, instructions, placeholders or examples."""
RETRY_PROMPT = PROMPT + '\nThe previous structure was invalid. Use JSON booleans/null, emotions as objects with a label key, and voice as an object. Return only supported audible observations.'


class ModelManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._admission_lock = threading.Lock()
        self._model: Any = None
        self._processor: Any = None
        self._last_activity = time.monotonic()
        self._stage = GPUStage("moss", int(os.getenv("MOSS_GPU_BUDGET_MIB", "12288")),
                               int(os.getenv("GPU_RESERVE_MIB", "1024")))
        self._busy = False
        self._waiting_for_gpu = False
        self._error: str | None = None
        self._last_release: dict[str, Any] | None = None
        self._load_count = 0
        self._last_load_seconds = None
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, name="moss-idle-reaper", daemon=True)
        self._reaper.start()

    def status(self) -> dict[str, Any]:
        resident = self._model is not None or allocator_state(torch, DEVICE)["reserved_mib"] > IDLE_RESERVED_MIB
        return {"idle_seconds": round(time.monotonic() - self._last_activity, 1) if not self._busy else 0, "loaded": self._model is not None, "resident": resident, "busy": self._busy, "waiting_for_gpu": self._waiting_for_gpu, "last_load_error": self._error, "last_release": self._last_release,
                "idle_unload_seconds": IDLE_UNLOAD_SECONDS, "unload_after_request": UNLOAD_AFTER_REQUEST,
                "load_count": self._load_count, "last_load_seconds": self._last_load_seconds,
                "reaper_running": self._reaper.is_alive()}

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            started = time.monotonic()
            try:
                self._stage.configure(torch, DEVICE)
                if os.getenv("MOSS_MODEL_ROOT"):
                    path = os.environ["MOSS_MODEL_ROOT"]
                    from sonovect_assets import verify_identity
                    verify_identity(path, MODEL_ID, MODEL_REVISION)
                else:
                    path = resolve_pinned_snapshot(
                        snapshot_download, repo_id=MODEL_ID, revision=MODEL_REVISION, logger=logger,
                    )
                # Hash verification can take tens of seconds. A capacity check
                # before that work is stale when allocator warmup starts: a
                # peer may have loaded its model while we verified the files.
                _require_gpu_capacity()
                self._model = MossAudioModel.from_pretrained(
                    path,
                    trust_remote_code=False,
                    local_files_only=True,
                    dtype="auto",
                    use_safetensors=True,
                    device_map=DEVICE,
                )
                self._model.eval()
                # Both catalogued checkpoints use this native tokenizer. The
                # upstream auto-loader drops trust_remote_code and can prompt
                # in a headless worker; the public constructor avoids that
                # dynamic configuration path with identical input tensors.
                self._processor = MossAudioProcessor(
                    Qwen2Tokenizer.from_pretrained(path, local_files_only=True),
                    enable_time_marker=True,
                )
                self._error = None
                self._load_count += 1
                self._last_load_seconds = round(time.monotonic() - started, 3)
                self._last_activity = time.monotonic()
            except Exception as exc:
                self._model = None
                self._processor = None
                self._error = str(exc)
                raise

    def unload(self, *, only_if_idle=False) -> dict[str, Any] | None:
        with self._lock:
            if only_if_idle and (self._busy or time.monotonic() - self._last_activity < IDLE_UNLOAD_SECONDS):
                return None
            if only_if_idle and self._model is None and allocator_state(torch, DEVICE)["reserved_mib"] <= IDLE_RESERVED_MIB:
                return None
            self._model = None
            self._processor = None
            self._last_release = release_idle_cuda(torch, DEVICE)
            return self._last_release

    def _reap_loop(self) -> None:
        while not self._stop.wait(10):
            if self._lock.acquire(blocking=False):
                try:
                    self.unload(only_if_idle=True)
                except Exception:
                    logger.exception("MOSS idle GPU release failed")
                finally:
                    self._lock.release()

    def analyze(self, waveform, sample_rate):
        with self._admission_lock:
            self._waiting_for_gpu = True
            try:
                self._waiting_for_gpu = False
                return self._analyze_with_models(waveform, sample_rate)
            finally:
                self._waiting_for_gpu = False
                self._last_activity = time.monotonic()

    def _analyze_with_models(self, waveform: Any, sample_rate: int) -> dict[str, Any]:
        with self._lock:
            if not len(waveform) or not waveform.any():
                result = _normalize({"vocal_present": False, "emotions": [], "voice": {}},
                    round(len(waveform) * 1000 / sample_rate), "", -180.0)
                result["structured_attempts"] = 0
                return result
            self._busy = True
            try:
                self._stage.begin(torch, DEVICE)
                self.load()
                duration_ms = round(len(waveform) * 1000 / sample_rate)
                rms = math.sqrt(float((waveform.astype("float64") ** 2).mean())) if len(waveform) else 0.0
                rms_db = 20.0 * math.log10(max(rms, 1e-9))
                attempts: list[str] = []
                for attempt in range(STRUCTURED_RETRIES + 1):
                    prompt = PROMPT if attempt == 0 else RETRY_PROMPT
                    inputs = self._processor(text=prompt, audios=[waveform], return_tensors="pt")
                    inputs = inputs.to(self._model.device)
                    if inputs.get("audio_data") is not None:
                        inputs["audio_data"] = inputs["audio_data"].to(self._model.dtype)
                    inputs["audio_input_mask"] = inputs["input_ids"] == self._processor.audio_token_id
                    with torch.inference_mode():
                        generated = self._model.generate(
                            **inputs,
                            max_new_tokens=MAX_NEW_TOKENS,
                            do_sample=False,
                            num_beams=1,
                            use_cache=True,
                        )
                    input_len = inputs["input_ids"].shape[1]
                    text = self._processor.decode(generated[0, input_len:], skip_special_tokens=True).strip()
                    attempts.append(text)
                    payload = _parse_json(text)
                    if payload:
                        result = _normalize(payload, duration_ms, text, rms_db)
                        result["structured_attempts"] = attempt + 1
                        if result["vocal_valid"]:
                            return result
                        logger.warning("moss_structured_output_invalid attempt=%s reason=vocal_structure characters=%s",
                                       attempt + 1, len(text))
                        if attempt == STRUCTURED_RETRIES:
                            return result
                    else:
                        logger.warning("moss_structured_output_invalid attempt=%s reason=json characters=%s",
                                       attempt + 1, len(text))
                result = _normalize({}, duration_ms, attempts[-1] if attempts else "", rms_db)
                result["structured_attempts"] = len(attempts)
                return result
            finally:
                try:
                    self._stage.finish(torch, DEVICE)
                except Exception:
                    logger.exception("GPU stage telemetry unavailable")
                self._busy = False


def _parse_json(text: str) -> dict[str, Any]:
    # Thinking checkpoints may propose JSON inside reasoning. Only the final
    # answer can become an observation; a truncated reasoning block is invalid.
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    elif "<think>" in text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalize(payload: dict[str, Any], duration_ms: int, raw: str, rms_db: float) -> dict[str, Any]:
    presence = payload.get("vocal_present")
    presence_valid = "vocal_present" in payload and (presence is None or type(presence) is bool)
    present = presence_valid and presence is True
    allowed = ("accent", "pitch", "volume", "speed", "texture", "clarity", "fluency", "tone")
    structure_valid = (isinstance(payload.get("emotions"), list)
        and isinstance(payload.get("voice"), dict)
        and all(isinstance(x, dict) and isinstance(x.get("label"), str) and x["label"] in EMOTIONS for x in payload.get("emotions", []))
        and all(isinstance(v, str) for k, v in payload.get("voice", {}).items() if k in allowed))
    consistent = (isinstance(payload.get("emotions"), list) and len(payload["emotions"]) == 1 if present else
                  not payload.get("emotions") and not payload.get("voice"))
    warnings = [] if present else ["vocal_presence_uncertain" if presence is None else "vocal_not_detected"]
    emotions: list[dict[str, Any]] = []
    for item in payload.get("emotions", []) if present and isinstance(payload.get("emotions"), list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).upper()
        if label not in EMOTIONS:
            continue
        emotions.append({"label": label, "start_ms": 0, "end_ms": duration_ms, "confidence": None, "temporal_resolution": "analysis-window"})

    voice = payload.get("voice") if present and isinstance(payload.get("voice"), dict) else {}
    placeholders = {
        "普通话或可听出的口音特征", "偏高/中等/偏低及变化", "偏大/中等/偏小及变化",
        "偏快/中等/偏慢及节奏", "音色和质感", "清晰度和含混程度", "流利度、停顿或重复",
        "语气和表达方式", "环境声、混响、音乐或噪声", "一句话声音概述", "无法判断",
    }
    placeholder_fragments = ("可听出的", "及变化", "和含混程度", "流利度、停顿", "环境声、混响", "一句话声音概述")
    voice = {
        key: value for key in allowed
        if (value := audible_description(voice.get(key, "")))
        and value not in placeholders
        and not any(fragment in value for fragment in placeholder_fragments)
    }
    return {
        "duration_ms": duration_ms,
        "emotions": emotions,
        "vocal_valid": presence_valid and structure_valid and consistent,
        "vocal_present": presence if presence_valid else None,
        "warnings": warnings,
        "voice": voice,
        "signal": {"rms_db": round(rms_db, 2)},
        "parse_valid": bool(payload),
        "raw_description": raw if DEBUG_RAW or not payload else None,
    }


def _offset(items: list[dict[str, Any]], offset_ms: int) -> list[dict[str, Any]]:
    return [{**item, "start_ms": item["start_ms"] + offset_ms, "end_ms": item["end_ms"] + offset_ms} for item in items]


manager = ModelManager()
app = FastAPI(title="Sonovect optional vocal analysis", version=APP_VERSION)
ANALYSIS_REQUESTS = 0


@app.get("/health")
async def health() -> dict[str, Any]:
    access = await asyncio.to_thread(gpu_health, DEVICE)
    gpu = None
    if access["available"] and torch.cuda.is_available():
        gpu = {"name": torch.cuda.get_device_name(0), "allocated_mb": int(torch.cuda.memory_allocated(0) / 1024**2), "reserved_mb": int(torch.cuda.memory_reserved(0) / 1024**2)}
    return {

        "status": "ok" if access["available"] and manager.status()["last_load_error"] is None and not (manager._last_release and not manager._last_release["confirmed"] and not manager._busy) else "degraded",
        "version": APP_VERSION,
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "stage": "vocal", "analysis_requests": ANALYSIS_REQUESTS,
        "vocal_schema": "presence-gated-v1",
        "gpu": gpu,
        "gpu_access": access,
        "manager": manager.status(),
        "resource_contract": manager._stage.status(),
    }


@app.get("/ready")
async def ready():
    state = await health()
    return JSONResponse(state, status_code=200 if state["status"] == "ok" else 503)


@app.post("/internal/load")
async def load_models() -> dict[str, Any]:
    try:
        def scheduled_load():
            with manager._admission_lock:
                manager.load()
        await asyncio.to_thread(scheduled_load)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "loaded", "manager": manager.status()}


@app.post("/internal/unload")
async def unload_models() -> dict[str, Any]:
    if manager._busy:
        raise HTTPException(status_code=409, detail="GPU computation active")
    release = await asyncio.to_thread(manager.unload)
    if not release["confirmed"]:
        return JSONResponse({"status": "release_failed", "manager": manager.status()}, status_code=503)
    return {"status": "unloaded", "manager": manager.status()}


@app.post("/analyze")
async def analyze(files: Annotated[list[UploadFile], File(description="Audio files")]) -> dict[str, Any]:
    global ANALYSIS_REQUESTS
    ANALYSIS_REQUESTS += 1
    outputs: list[dict[str, Any]] = []
    temp_paths: list[Path] = []
    request_failed = False
    try:
        for upload in files:
            suffix = Path(upload.filename or "audio.wav").suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(await upload.read())
                path = Path(handle.name)
            temp_paths.append(path)
            waveform, sample_rate = librosa.load(path, sr=16_000, mono=True)
            chunk_samples = MAX_CHUNK_SECONDS * sample_rate
            chunks: list[dict[str, Any]] = []
            for start in range(0, len(waveform), chunk_samples):
                chunk = waveform[start : start + chunk_samples]
                if chunk.size == 0:
                    continue
                value = await asyncio.to_thread(manager.analyze, chunk, sample_rate)
                offset_ms = round(start * 1000 / sample_rate)
                value["emotions"] = _offset(value["emotions"], offset_ms)
                value["offset_ms"] = offset_ms
                chunks.append(value)
            voice_observations = [
                {"label": value, "kind": name, "start_ms": int(chunk["offset_ms"]),
                 "end_ms": int(chunk["offset_ms"]) + int(chunk["duration_ms"]), "temporal_resolution": "analysis-window"}
                for chunk in chunks for name, value in chunk["voice"].items()]
            warnings = {warning for chunk in chunks for warning in chunk["warnings"]}
            if any(chunk["vocal_present"] is True for chunk in chunks):
                warnings.discard("vocal_not_detected")
            outputs.append({"engine": {"model": MODEL_ID, "revision": MODEL_REVISION},
                "duration_ms": round(len(waveform) * 1000 / sample_rate),
                "emotions": [item for chunk in chunks for item in chunk["emotions"]],
                "voice": voice_observations, "parse_valid": all(chunk["parse_valid"] for chunk in chunks),
                "vocal_valid": all(chunk["vocal_valid"] for chunk in chunks),
                "warnings": sorted(warnings),
                "raw_description": [chunk["raw_description"] for chunk in chunks] if DEBUG_RAW else None})
    except Exception as exc:
        request_failed = True
        # A failed from_pretrained call can leave a partially constructed CUDA
        # model reachable only through the exception traceback.  The request
        # finally block runs while that traceback is still live, so ordinary
        # gc/empty_cache cannot release the allocation.  Detach the traceback
        # before cleanup and return a fresh transport exception without chaining.
        # Keep formatted text, never exc_info/traceback objects that retain a
        # partially constructed CUDA model during the following cleanup.
        failure_type = type(exc).__name__
        diagnostic = "".join(traceback.format_exception(exc))
        message = detach_exception(exc)
        logger.error("moss_analysis_failed type=%s: %s\n%s", failure_type, message, diagnostic)
        del exc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        raise HTTPException(status_code=500, detail=message) from None
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)
        if UNLOAD_AFTER_REQUEST or request_failed:
            await asyncio.to_thread(manager.unload)
    return outputs[0] if len(outputs) == 1 else {"results": outputs}
