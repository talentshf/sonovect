from __future__ import annotations

from gpu_health import gpu_health
from fastapi.responses import JSONResponse

import asyncio
import difflib
import gc
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

import librosa
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from huggingface_hub import snapshot_download
from typing_extensions import Annotated

from text_utils import trim_rolling_context_prefix
from timestamp_utils import offset_word_spans, validated_word_spans
from snapshot_cache import resolve_pinned_snapshot
from gpu_capacity import wait_for_capacity
from gpu_stage import GPUStage
from batching import batch_ranges, checked_results


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("qwen3-asr-worker")

from sonovect_version import VERSION as APP_VERSION
from runtime_config import validate_environment
validate_environment()
ASR_BACKEND = "qwen"
MODEL_ID = os.getenv("QWEN_ASR_MODEL", "Qwen/Qwen3-ASR-1.7B-hf")
MODEL_REVISION = os.getenv("QWEN_ASR_REVISION", "bcd2b5b7f32b480ab5790554cfa8347f246a14f3")
ALIGNER_ID = os.getenv("QWEN_ALIGNER_MODEL", "Qwen/Qwen3-ForcedAligner-0.6B-hf")
ALIGNER_REVISION = os.getenv("QWEN_ALIGNER_REVISION", "c07281df297b9905d24a508279258cccf987a064")
DEVICE = os.getenv("QWEN_DEVICE", "cuda:0")
DTYPE_NAME = os.getenv("QWEN_DTYPE", "bfloat16")
IDLE_UNLOAD_SECONDS = int(os.getenv("QWEN_IDLE_UNLOAD_SECONDS", "300"))
MAX_NEW_TOKENS = int(os.getenv("QWEN_MAX_NEW_TOKENS", "2048"))
MAX_BATCH_SIZE = int(os.getenv("QWEN_MAX_BATCH_SIZE", "1"))
MAX_BATCH_AUDIO_SECONDS = float(os.getenv("QWEN_MAX_BATCH_AUDIO_SECONDS", "60"))
ATTENTION_IMPLEMENTATION = os.getenv("QWEN_ATTENTION_IMPLEMENTATION", "auto")
if not 1 <= MAX_BATCH_SIZE <= 4 or MAX_BATCH_AUDIO_SECONDS <= 0:
    raise RuntimeError("qwen_batch_limits_invalid")
if ATTENTION_IMPLEMENTATION not in {"auto", "sdpa", "eager", "flash_attention_2"}:
    raise RuntimeError("qwen_attention_implementation_invalid")
DEFAULT_CONTEXT = os.getenv("QWEN_DEFAULT_CONTEXT", "").strip()
ROLLING_CONTEXT_CHARS = int(os.getenv("QWEN_ROLLING_CONTEXT_CHARS", "0"))
MIN_FREE_GPU_BYTES = int(float(os.getenv("QWEN_MIN_FREE_GIB", "6")) * 1024**3)

LANGUAGE_MAP = {
    "zh": "Chinese",
    "en": "English",
    "yue": "Cantonese",
    "ja": "Japanese",
    "ko": "Korean",
    "chinese": "Chinese",
    "english": "English",
    "cantonese": "Cantonese",
    "japanese": "Japanese",
    "korean": "Korean",
}


def _dtype() -> torch.dtype:
    if DTYPE_NAME == "float16":
        return torch.float16
    if DTYPE_NAME == "float32":
        return torch.float32
    return torch.bfloat16


def _require_gpu_capacity() -> None:
    if not DEVICE.startswith("cuda"):
        return
    wait_for_capacity(
        lambda: torch.cuda.mem_get_info(DEVICE), max(MIN_FREE_GPU_BYTES,
            (int(os.getenv("QWEN_GPU_BUDGET_MIB", "8192")) + int(os.getenv("GPU_RESERVE_MIB", "1024"))) * 1024**2),
        timeout=float(os.getenv("GPU_CAPACITY_WAIT_SECONDS", "360")),
        on_wait=lambda waiting: setattr(manager, "_waiting_for_gpu", waiting),
    )


def _normalize_language(language: str) -> Optional[str]:
    value = language.strip()
    if not value or value.lower() == "auto":
        return None
    return LANGUAGE_MAP.get(value.lower(), value)


def _configured_context_echo(text: str) -> bool:
    if not DEFAULT_CONTEXT or len(text) < 24:
        return False
    compact = lambda value: re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()
    candidate = compact(text)
    configured = compact(DEFAULT_CONTEXT)
    if len(candidate) < 20 or len(configured) < 20:
        return False
    return candidate in configured or difflib.SequenceMatcher(None, candidate, configured).ratio() >= 0.78


class LazyModelManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._admission_lock = threading.Lock()
        self._model: Optional[Any] = None
        self._last_used = 0.0
        self._last_activity = time.monotonic()
        self._loaded_at = 0.0
        self._load_error: Optional[str] = None
        self._batch_fallbacks = 0
        self._last_batch_size = 0
        self._last_audio_seconds = 0.0
        self._needs_cleanup = False
        self._stage = GPUStage("qwen", int(os.getenv("QWEN_GPU_BUDGET_MIB", "8192")),
                               int(os.getenv("GPU_RESERVE_MIB", "1024")))
        self._busy = False
        self._waiting_for_gpu = False
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, name="qwen-idle-reaper", daemon=True)
        self._reaper.start()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def status(self) -> dict[str, Any]:
        # Inference intentionally holds _lock so unload and concurrent requests
        # cannot mutate the model. Health checks must remain observable while a
        # long request owns that lock, so status only reads atomic Python fields.
        return {
            "loaded": self._model is not None,
            "resident": self._model is not None or self._needs_cleanup,
            "busy": self._busy,
            "waiting_for_gpu": self._waiting_for_gpu,
            "loaded_at_epoch": round(self._loaded_at, 3) if self._loaded_at else None,
            "last_used_epoch": round(self._last_used, 3) if self._last_used else None,
            "idle_unload_seconds": IDLE_UNLOAD_SECONDS,
            "idle_seconds": round(time.monotonic() - self._last_activity, 1) if not self._busy else 0,
            "last_load_error": self._load_error,
            "max_batch_size": MAX_BATCH_SIZE,
            "max_batch_audio_seconds": MAX_BATCH_AUDIO_SECONDS,
            "attention_implementation": ATTENTION_IMPLEMENTATION,
            "last_batch_size": self._last_batch_size,
            "last_audio_seconds": round(self._last_audio_seconds, 3),
            "batch_oom_fallbacks": self._batch_fallbacks,
        }

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                self._last_used = time.time()
                self._last_activity = time.monotonic()
                return
            if DEVICE.startswith("cuda") and not torch.cuda.is_available():
                raise RuntimeError("CUDA is required but not available")
            self._stage.configure(torch, DEVICE)
            logger.info("Resolving pinned Qwen model snapshots")
            try:
                model_path = resolve_pinned_snapshot(
                    snapshot_download, repo_id=MODEL_ID, revision=MODEL_REVISION, logger=logger,
                )
                from native_runtime import NativeQwenASR
                aligner_path = resolve_pinned_snapshot(
                    snapshot_download, repo_id=ALIGNER_ID, revision=ALIGNER_REVISION, logger=logger,
                )
                logger.info("Loading Qwen3-ASR and ForcedAligner on %s", DEVICE)
                self._needs_cleanup = True
                attention_kwargs = {} if ATTENTION_IMPLEMENTATION == "auto" else {
                    "attn_implementation": ATTENTION_IMPLEMENTATION,
                }
                # Snapshot checks perform CPU/disk work; measure current free
                # memory only after both snapshots are verified, just before
                # the framework allocates the model and aligner on the GPU.
                _require_gpu_capacity()
                self._model = NativeQwenASR.from_pretrained(
                    model_path,
                    dtype=_dtype(),
                    device_map=DEVICE,
                    max_inference_batch_size=MAX_BATCH_SIZE,
                    max_new_tokens=MAX_NEW_TOKENS,
                    forced_aligner=aligner_path,
                    forced_aligner_kwargs={"dtype": _dtype(), "device_map": DEVICE, **attention_kwargs},
                    **attention_kwargs,
                )
                self._loaded_at = time.time()
                self._last_used = self._loaded_at
                self._last_activity = time.monotonic()
                self._load_error = None
                logger.info("Qwen3-ASR models loaded")
            except Exception as exc:
                self._load_error = str(exc)
                self._model = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                raise

    def unload(self, *, only_if_idle: bool = False) -> bool:
        with self._lock:
            if only_if_idle and (
                self._busy or IDLE_UNLOAD_SECONDS <= 0
                or time.monotonic() - self._last_activity < IDLE_UNLOAD_SECONDS
            ):
                return False
            if self._model is None and not self._needs_cleanup:
                return False
            logger.info("Unloading Qwen3-ASR models after idle period")
            self._model = None
            self._loaded_at = 0.0
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self._needs_cleanup = False
            return True

    def transcribe(self, audios, languages, contexts, context_keys):
        if not (len(audios) == len(languages) == len(contexts) == len(context_keys)):
            raise ValueError("audio, language, context, and context key counts must match")
        histories = {}
        results = []
        with self._admission_lock:
            for start, end in batch_ranges(
                audios, context_keys,
                size=MAX_BATCH_SIZE,
                seconds=MAX_BATCH_AUDIO_SECONDS, rolling=ROLLING_CONTEXT_CHARS > 0,
            ):
                audio, language, context, context_key = audios[start], languages[start], contexts[start], context_keys[start]
                previous = histories.get(context_key, "")
                if previous and ROLLING_CONTEXT_CHARS > 0:
                    context = context + "\n上一段同一说话人的转写，仅用于保持术语和语境连续。上下文本身不是录音；当前音频若实际再次说出这些内容，必须如实保留：" + previous[-ROLLING_CONTEXT_CHARS:]
                self._waiting_for_gpu = True
                try:
                    self._waiting_for_gpu = False
                    batch_contexts = [context] if ROLLING_CONTEXT_CHARS > 0 else contexts[start:end]
                    batch_results = self._transcribe_batch(
                        audios[start:end], languages[start:end], batch_contexts, context_keys[start:end],
                    )
                finally:
                    self._waiting_for_gpu = False
                results.extend(checked_results(batch_results, end - start))
                for key, result in zip(context_keys[start:end], batch_results):
                    text = str(getattr(result, "text", "")).strip()
                    if text:
                        histories[key] = text
        return results

    def _transcribe_batch(
        self,
        audios: list[tuple[Any, int]],
        languages: list[Optional[str]],
        contexts: list[str],
        context_keys: list[str],
    ) -> list[Any]:
        with self._lock:
            self._busy = True
            try:
                self._stage.begin(torch, DEVICE)
                self.load()
                if self._model is None:
                    raise RuntimeError("Qwen3-ASR model failed to load")
                if not (len(audios) == len(languages) == len(contexts) == len(context_keys)):
                    raise ValueError("audio, language, context, and context key counts must match")
                self._last_batch_size = len(audios)
                self._last_audio_seconds = sum(len(audio) / sr for audio, sr in audios)
                if ROLLING_CONTEXT_CHARS <= 0:
                    results = []
                    for start, end in batch_ranges(audios, context_keys, size=MAX_BATCH_SIZE, seconds=MAX_BATCH_AUDIO_SECONDS):
                        try:
                            batch = self._model.transcribe(
                                audio=audios[start:end], context=[v.strip() for v in contexts[start:end]],
                                language=languages[start:end], return_time_stamps=True,
                            )
                        except torch.cuda.OutOfMemoryError as exc:
                            if end - start == 1:
                                raise
                            exc.__traceback__ = None
                            del exc
                            gc.collect()
                            torch.cuda.empty_cache()
                            self._batch_fallbacks += 1
                            logger.warning("ASR batch exceeded its GPU budget; retrying individual segments")
                            batch = []
                            for index in range(start, end):
                                batch.extend(checked_results(self._model.transcribe(
                                    audio=[audios[index]], context=contexts[index].strip(),
                                    language=languages[index], return_time_stamps=True,
                                ), 1))
                        results.extend(checked_results(batch, end - start))
                    return results
                histories: dict[str, str] = {}
                results: list[Any] = []
                for audio, language, base_context, context_key in zip(
                    audios,
                    languages,
                    contexts,
                    context_keys,
                ):
                    prompt_parts = [base_context.strip()] if base_context.strip() else []
                    previous = histories.get(context_key, "")
                    if previous and ROLLING_CONTEXT_CHARS > 0:
                        prompt_parts.append(
                            "上一段同一说话人的转写，仅用于保持术语和语境连续。上下文本身不是录音；当前音频若实际再次说出这些内容，必须如实保留："
                            + previous[-ROLLING_CONTEXT_CHARS:]
                        )
                    result = self._model.transcribe(
                        audio=[audio],
                        context="\n".join(prompt_parts),
                        language=language,
                        return_time_stamps=True,
                    )[0]
                    results.append(result)
                    text = str(getattr(result, "text", "")).strip()
                    if text:
                        histories[context_key] = text
                    self._last_used = time.time()
                self._last_activity = time.monotonic()
                return results
            finally:
                try:
                    self._stage.finish(torch, DEVICE)
                except Exception:
                    logger.exception("GPU stage telemetry unavailable")
                self._last_used = time.time()
                self._last_activity = time.monotonic()
                self._busy = False

    def _reap_loop(self) -> None:
        while not self._stop.wait(10):
            # Keep decision and release under the same lock. A new request may
            # have finished after a previous timer tick decided to unload.
            if self._lock.acquire(blocking=False):
                try:
                    self.unload(only_if_idle=True)
                except Exception:
                    logger.exception("Qwen idle unload failed")
                finally:
                    self._lock.release()



manager = LazyModelManager()
app = FastAPI(title="Sonovect Qwen ASR", version=APP_VERSION)


def _engine() -> dict[str, Any]:
    return {
        "name": "Qwen3-ASR",
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "forced_aligner": ALIGNER_ID,
        "forced_aligner_revision": ALIGNER_REVISION,
        "mode": "primary",
        "timestamp_origin": "forced-aligner",
        "capability_gaps": [],
        "context_strategy": "configured-terms-plus-same-speaker-rolling-v1",
    }


def _word_items(result: Any, duration_ms: int) -> list[dict[str, Any]]:
    aligned = getattr(result, "time_stamps", None)
    items = getattr(aligned, "items", []) if aligned is not None else []
    try:
        words = [
            {"text": str(item.text), "start_ms": round(float(item.start_time) * 1000),
             "end_ms": round(float(item.end_time) * 1000), "confidence": getattr(item, "confidence", None)}
            for item in items
        ]
    except (TypeError, ValueError, AttributeError, OverflowError):
        return []
    return validated_word_spans(words, duration_ms)


def _result_payload(result: Any, duration_ms: int) -> dict[str, Any]:
    if hasattr(result, "joint_segments"):
        segments = result.joint_segments
        turns = [{"start_ms": s["start_ms"], "end_ms": s["end_ms"], "speaker": s["speaker"],
                  "overlap": any(o["speaker"] != s["speaker"] and min(o["end_ms"], s["end_ms"]) > max(o["start_ms"], s["start_ms"]) for o in segments),
                  "confidence": None} for s in segments]
        return dict(text=result.text, raw_text=result.text, language=result.language, duration_ms=duration_ms,
                    segments=segments, words=[], speaker_turns=turns, joint_diarization=True, engine=_engine())
    words = _word_items(result, duration_ms)
    end_ms = max([word["end_ms"] for word in words], default=duration_ms)
    text = str(getattr(result, "text", "")).strip()
    language = str(getattr(result, "language", "") or "unknown")
    segments = []
    if text:
        segments.append(
            {
                "start_ms": 0,
                "end_ms": max(duration_ms, end_ms),
                "text": text,
                "raw_text": text,
                "speaker": None,
                "language": language,
                "emotions": [],
                "events": [],
                **({"words": words} if words else {}),
            }
        )
    return {
        "text": text,
        "raw_text": text,
        "language": language,
        "duration_ms": max(duration_ms, end_ms),
        "segment_count": len(segments),
        "segments": segments,
        **({"words": words} if words or not text else {}),
        "engine": _engine(),
    }


def _parse_segment_plan(value: Optional[str], file_count: int) -> tuple[dict[str, Any], list[list[dict[str, Any]]]]:
    if not value:
        return {}, [[] for _ in range(file_count)]
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid segment_plan JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise HTTPException(status_code=400, detail="segment_plan must contain a files list")
    files: list[list[dict[str, Any]]] = []
    for index in range(file_count):
        raw = payload["files"][index] if index < len(payload["files"]) else []
        files.append([item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else [])
    metadata = {key: value for key, value in payload.items() if key != "files"}
    return metadata, files


def _segmented_payload(
    results: list[Any],
    chunks: list[dict[str, Any]],
    duration_ms: int,
    segmentation: dict[str, Any],
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    all_words: list[dict[str, Any]] = []
    texts: list[str] = []
    languages: list[str] = []
    previous_text_by_speaker: dict[str, str] = {}
    missing_alignment = False
    for result, chunk in zip(results, chunks):
        chunk_duration_ms = int(chunk["audio_end_ms"]) - int(chunk["audio_start_ms"])
        words = offset_word_spans(
            _word_items(result, chunk_duration_ms),
            int(chunk["audio_start_ms"]),
        )
        text = str(getattr(result, "text", "")).strip()
        speaker_key = str(chunk.get("speaker") or "unknown")
        text, words, removed_context_characters = (trim_rolling_context_prefix(
            previous_text_by_speaker.get(speaker_key, ""),
            text,
            words,
            maximum_overlap_characters=ROLLING_CONTEXT_CHARS,
            maximum_removed_end_ms=int(chunk["start_ms"]),
        ))
        # A context-like phrase may have actually been spoken. Retain it for
        # review; the coordinator's VAD evidence handles no-speech hallucination.
        configured_context_echo_suspected = _configured_context_echo(text)
        if text:
            previous_text_by_speaker[speaker_key] = text
        detected_language = str(getattr(result, "language", "") or "unknown")
        if text:
            texts.append(text)
            missing_alignment = missing_alignment or not words
        if detected_language != "unknown":
            languages.append(detected_language)
        all_words.extend(words)
        segments.append(
            {
                "start_ms": int(chunk["start_ms"]),
                "end_ms": int(chunk["end_ms"]),
                "audio_start_ms": int(chunk["audio_start_ms"]),
                "audio_end_ms": int(chunk["audio_end_ms"]),
                "text": text,
                "raw_text": text,
                "speaker": chunk.get("speaker"),
                "language": detected_language,
                "routing_language": chunk.get("language"),
                "emotions": [],
                "events": [],
                **({"words": words} if words else {}),
                "removed_rolling_context_characters": removed_context_characters,
                "configured_context_echo_removed": False,
                "configured_context_echo_suspected": configured_context_echo_suspected,
            }
        )
    unique_languages = list(dict.fromkeys(languages))
    return {
        "text": "\n".join(texts),
        "raw_text": "\n".join(texts),
        "language": unique_languages[0] if len(unique_languages) == 1 else "mixed" if unique_languages else "unknown",
        "duration_ms": duration_ms,
        "segment_count": len(segments),
        "segments": segments,
        **({"words": all_words} if not missing_alignment else {}),
        "segmentation": {**segmentation, "segment_count": len(segments)},
        "engine": _engine(),
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    access = await asyncio.to_thread(gpu_health, DEVICE)
    gpu = None
    if access["available"] and torch.cuda.is_available():
        gpu = {
            "name": torch.cuda.get_device_name(0),
            "allocated_mb": round(torch.cuda.memory_allocated(0) / 1024**2),
            "reserved_mb": round(torch.cuda.memory_reserved(0) / 1024**2),
        }
    return {

        "status": "ok" if access["available"] and manager.status()["last_load_error"] is None else "degraded",
        "version": APP_VERSION,
        "mode": "primary",
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "aligner": ALIGNER_ID,
        "aligner_revision": ALIGNER_REVISION,
        "device": DEVICE,
        "gpu": gpu,
        "gpu_access": access,
        "manager": manager.status(),
        "resource_contract": manager._stage.status(),
        "context": {
            "strategy": "configured-terms-plus-same-speaker-rolling-v1",
            "default_configured": bool(DEFAULT_CONTEXT),
            "rolling_chars": ROLLING_CONTEXT_CHARS,
        },
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
    await asyncio.to_thread(manager.unload)
    return {"status": "unloaded", "manager": manager.status()}


@app.post("/transcribe")
async def transcribe(
    files: Annotated[list[UploadFile], File(description="Audio files")],
    language: Annotated[str, Form()] = "auto",
    use_itn: Annotated[bool, Form()] = True,
    ban_emo_unk: Annotated[bool, Form()] = True,
    context: Annotated[str, Form()] = "",
    segment_plan: Annotated[Optional[str], Form()] = None,
) -> dict[str, Any]:
    del use_itn, ban_emo_unk
    audio_inputs: list[tuple[Any, int]] = []
    chunk_metadata: list[dict[str, Any]] = []
    chunk_file_indexes: list[int] = []
    chunk_languages: list[Optional[str]] = []
    chunk_contexts: list[str] = []
    chunk_context_keys: list[str] = []
    waveforms: list[Any] = []
    durations_ms: list[int] = []
    temp_paths: list[Path] = []
    try:
        for upload in files:
            suffix = Path(upload.filename or "audio.wav").suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(await upload.read())
                path = Path(handle.name)
            temp_paths.append(path)
            waveform, sample_rate = librosa.load(path, sr=16000, mono=True)
            waveforms.append(waveform)
            durations_ms.append(round(len(waveform) * 1000 / sample_rate))

        segmentation, file_plans = _parse_segment_plan(segment_plan, len(waveforms))
        for file_index, waveform in enumerate(waveforms):
            duration_ms = durations_ms[file_index]
            # The coordinator sends an explicit empty plan when VAD found no
            # speech. Do not replace that with a full-duration ASR request.
            if segment_plan and not file_plans[file_index]:
                continue
            plans = file_plans[file_index]
            if not plans:
                plans = [
                    {
                        "start_ms": 0,
                        "end_ms": duration_ms,
                        "audio_start_ms": 0,
                        "audio_end_ms": duration_ms,
                        "speaker": None,
                        "language": language,
                    }
                ]
            for plan in plans:
                audio_start_ms = max(0, min(duration_ms, int(plan.get("audio_start_ms", plan.get("start_ms", 0)))))
                audio_end_ms = max(0, min(duration_ms, int(plan.get("audio_end_ms", plan.get("end_ms", duration_ms)))))
                if audio_end_ms <= audio_start_ms:
                    continue
                start_sample = round(audio_start_ms * 16)
                end_sample = round(audio_end_ms * 16)
                audio_inputs.append((waveform[start_sample:end_sample], 16000))
                chunk_metadata.append(
                    {
                        **plan,
                        "start_ms": max(0, int(plan.get("start_ms", audio_start_ms))),
                        "end_ms": min(duration_ms, int(plan.get("end_ms", audio_end_ms))),
                        "audio_start_ms": audio_start_ms,
                        "audio_end_ms": audio_end_ms,
                    }
                )
                chunk_file_indexes.append(file_index)
                chunk_languages.append(_normalize_language(str(plan.get("language", language))))
                request_context = context.strip()
                chunk_contexts.append("\n".join(value for value in (DEFAULT_CONTEXT, request_context) if value))
                speaker = str(plan.get("speaker") or "unknown")
                chunk_context_keys.append(f"file-{file_index}:{speaker}")

        if not audio_inputs:
            payloads = [_segmented_payload([], [], duration, segmentation) for duration in durations_ms]
            return payloads[0] if len(payloads) == 1 else {"results": payloads}

        try:
            results = await asyncio.to_thread(
                manager.transcribe,
                audio_inputs,
                chunk_languages,
                chunk_contexts,
                chunk_context_keys,
            )
        except Exception as exc:
            logger.exception("Qwen3-ASR inference failed")
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        payloads = []
        for file_index, duration_ms in enumerate(durations_ms):
            indexes = [index for index, value in enumerate(chunk_file_indexes) if value == file_index]
            file_results = [results[index] for index in indexes]
            file_chunks = [chunk_metadata[index] for index in indexes]
            if not file_results:
                payloads.append(_segmented_payload([], [], duration_ms, segmentation))
            elif segment_plan:
                payloads.append(_segmented_payload(file_results, file_chunks, duration_ms, segmentation))
            else:
                payloads.append(_result_payload(file_results[0], duration_ms))
        return payloads[0] if len(payloads) == 1 else {"results": payloads}
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)
