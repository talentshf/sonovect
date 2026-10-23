from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from typing_extensions import Annotated

from segmentation import build_request_plan
from speaker_alignment import align_speakers


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sonovect-speech-coordinator")

from sonovect_version import VERSION as APP_VERSION
from runtime_config import validate_environment
validate_environment()
SEGMENTATION_URL = os.getenv("SEGMENTATION_URL", "http://speech-segmentation-worker:8082").rstrip("/")
QWEN_URL = os.getenv("QWEN_URL", "http://qwen3-asr-worker:8081").rstrip("/")
MOSS_URL = os.getenv("VOICE_URL", os.getenv("MOSS_URL", "http://moss-audio-worker:8083")).rstrip("/")
VOICE_BACKEND = os.getenv("VOICE_BACKEND", "moss")
SOUND_ENABLED = os.getenv("SOUND_ENABLED", "false").lower() in {"true", "1", "yes"}
SEGMENTATION_TIMEOUT = float(os.getenv("SEGMENTATION_TIMEOUT_SECONDS", "600"))
QWEN_TIMEOUT = float(os.getenv("QWEN_TIMEOUT_SECONDS", "1800"))
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() in {"true", "1", "yes"}
EVENTS_URL = os.getenv("EVENTS_URL", "http://speech-events:8084").rstrip("/")
EVENTS_TIMEOUT = float(os.getenv("EVENTS_TIMEOUT_SECONDS", "600"))
MEASUREMENTS_ENABLED = os.getenv("MEASUREMENTS_ENABLED", "false").lower() in {"true", "1", "yes"}
MEASUREMENTS_URL = os.getenv("MEASUREMENTS_URL", "http://speech-measurements:8086").rstrip("/")
MEASUREMENTS_TIMEOUT = float(os.getenv("MEASUREMENTS_TIMEOUT_SECONDS", "600"))
MOSS_TIMEOUT = float(os.getenv("MOSS_TIMEOUT_SECONDS", "3600"))
SEGMENT_TARGET_MS = int(os.getenv("SEGMENT_TARGET_MS", "30000"))
SEGMENT_HARD_MAX_MS = int(os.getenv("SEGMENT_HARD_MAX_MS", "90000"))
SEGMENT_MERGE_GAP_MS = int(os.getenv("SEGMENT_MERGE_GAP_MS", "3000"))
SEGMENT_BOUNDARY_SILENCE_MS = int(os.getenv("SEGMENT_BOUNDARY_SILENCE_MS", "700"))
SEGMENT_PADDING_MS = int(os.getenv("SEGMENT_PADDING_MS", "1000"))
MIN_TEXT_DENSITY = float(os.getenv("MIN_TEXT_DENSITY_PER_SPEECH_SECOND", "0.2"))

app = FastAPI(title="Sonovect speech coordinator", version=APP_VERSION)
STARTED_AT = time.time()
GPU_PIPELINE_LOCK = asyncio.Lock()


class AudioPart:
    def __init__(self, filename: str, content: bytes, content_type: str) -> None:
        self.filename = filename
        self.content = content
        self.content_type = content_type

    def httpx(self) -> tuple[str, tuple[str, bytes, str]]:
        return ("files", (self.filename, self.content, self.content_type))


async def _read_parts(files: list[UploadFile]) -> list[AudioPart]:
    return [
        AudioPart(
            upload.filename or "audio.wav",
            await upload.read(),
            upload.content_type or "application/octet-stream",
        )
        for upload in files
    ]


async def _post_audio(url: str, path: str, parts: list[AudioPart], data: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            f"{url}{path}",
            data={key: str(value).lower() if isinstance(value, bool) else value for key, value in data.items()},
            files=[part.httpx() for part in parts],
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Upstream {path} returned {response.status_code}: {response.text[:500]}")
    return response.json()


async def _post_control(url: str, path: str, timeout: float = 120) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(f"{url}{path}")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Upstream {path} returned {response.status_code}: {response.text[:500]}")
    return response.json()


async def _release_sound_before_speech():
    """A retained or explicitly preloaded sound model must yield to ASR."""
    if not VOICE_ENABLED or VOICE_BACKEND != "moss":
        return
    probe = await _probe(MOSS_URL)
    if not probe["reachable"]:
        return  # ASR still has its own bounded free-memory admission check.
    if not probe.get("payload", {}).get("manager", {}).get("resident", False):
        return
    released = await _post_control(MOSS_URL, "/internal/unload")
    state = released.get("manager") or {}
    if released.get("status") != "unloaded" or state.get("resident", True) or state.get("busy", True):
        raise RuntimeError("sound_unload_not_confirmed")


def _payloads(payload: dict[str, Any], count: int) -> list[dict[str, Any]]:
    results = payload.get("results")
    values = list(results[:count]) if isinstance(results, list) else [payload]
    while len(values) < count:
        values.append({})
    return [value if isinstance(value, dict) else {} for value in values]


def _strict_stage_payloads(payload, count):
    if not isinstance(payload, dict):raise ValueError("invalid_acoustic_payload")
    values = payload.get("results", [payload])
    if not isinstance(values, list) or len(values) != count or any(not isinstance(x, dict) for x in values):
        raise ValueError("invalid_acoustic_result_count")
    return values


def _speech_ms(payload: dict[str, Any]) -> int:
    total = 0
    for item in payload.get("speech_regions", []) if isinstance(payload.get("speech_regions"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("start_ms"), (int, float)) and isinstance(item.get("end_ms"), (int, float)):
            total += max(0, round(float(item["end_ms"]) - float(item["start_ms"])))
    return total


def _linguistic_count(text: str) -> int:
    return sum(character.isalnum() or "\u3400" <= character <= "\u9fff" for character in text)


def _gate_sparse(payload: dict[str, Any], segmentation: dict[str, Any]) -> dict[str, Any]:
    speech_ms = _speech_ms(segmentation)
    text = str(payload.get("text", "")).strip()
    density = _linguistic_count(text) / max(0.001, speech_ms / 1000)
    if speech_ms == 0 or (_linguistic_count(text) > 0 and density < MIN_TEXT_DENSITY):
        payload = {**payload, "text": "", "raw_text": "", "segments": [], "words": [], "segment_count": 0}
    return payload


def _summary(
    segments: list[dict[str, Any]],
    emotions: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    speakers: set[str] = set()
    emotion_labels = [str(item.get("label") or "") for item in emotions if isinstance(item, dict) and item.get("label")]
    event_labels = [str(item.get("label") or "") for item in events if isinstance(item, dict) and item.get("label")]
    emotion_counts = Counter(emotion_labels)
    event_counts = Counter(event_labels)
    for segment in segments:
        if segment.get("speaker"):
            speakers.add(str(segment["speaker"]))
    return {
        "emotions": dict(emotion_counts),
        "events": dict(event_counts),
        "speaker_count": len(speakers),
    }


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail).splitlines()[0][:240]
    return type(exc).__name__


def _lane_state(*, requested: bool, error: str | None, complete: bool) -> dict[str, Any]:
    if not requested:
        return {"state": "not_requested", "error": None}
    return {"state": "completed" if complete and not error else "failed", "error": error}


def _compose(
    qwen: dict[str, Any],
    segmentation: dict[str, Any],
    moss: Optional[dict[str, Any]] = None,
    include_speaker_identity: bool = False,
    *,
    full: bool = False,
    speech_error: str | None = None,
    acoustic_error: str | None = None,
    events_data: Optional[dict[str, Any]] = None,
    events_error: str | None = None,
    voice: bool = False,
    measure: bool = False,
    measurement_data: Optional[dict[str, Any]] = None,
    measurement_error: str | None = None,
) -> dict[str, Any]:
    if qwen.get("joint_diarization"):
        segmentation = {**segmentation, "speaker_turns": qwen.get("speaker_turns", []),
                        "speaker_profiles": [], "diarization_model": qwen.get("engine", {}).get("model"),
                        "diarization_revision": qwen.get("engine", {}).get("revision"), "overlap_detection": True}
    if _speech_ms(segmentation) == 0:
        # A joint decoder can hallucinate both text and speakers on silence.
        # Keep VAD authoritative for the anonymous speaker timeline as well.
        segmentation = {**segmentation, "speaker_turns": [], "speaker_profiles": []}
    payload = _gate_sparse(qwen, segmentation)
    segments = [dict(item) for item in payload.get("segments", []) if isinstance(item, dict)]
    if segmentation.get("overlap_detection") and not qwen.get("joint_diarization"):
        segments = align_speakers(segments, segmentation.get("speaker_turns", []))
    emotions = moss.get("emotions", []) if isinstance(moss, dict) and isinstance(moss.get("emotions"), list) else []
    events = events_data.get("events", []) if isinstance(events_data, dict) and isinstance(events_data.get("events"), list) else []
    # Speech is represented by the ASR/VAD lane. Keeping MOSS' generic
    # `Speech` event in the acoustic lane would duplicate every conversation
    # as a full-width sound block and can leak the prompt example on silence.
    events = [item for item in events if isinstance(item, dict) and str(item.get("kind") or "").lower() != "speech" and str(item.get("label") or "").lower() != "speech"]
    if _speech_ms(segmentation) == 0:
        emotions = []
    duration_ms = int(segmentation.get("duration_ms") or (moss.get("duration_ms") if isinstance(moss, dict) else 0) or 0)
    speech_regions = segmentation.get("speech_regions", []) if isinstance(segmentation.get("speech_regions"), list) else []
    clustering = segmentation.get("speaker_clustering") if isinstance(segmentation.get("speaker_clustering"), dict) else {}
    selection = clustering.get("selection") if isinstance(clustering.get("selection"), dict) else {}
    turn_speakers = {turn.get("speaker") for turn in (segmentation.get("speaker_turns") or []) if isinstance(turn, dict)}
    profile_speakers = {profile.get("speaker") for profile in (segmentation.get("speaker_profiles") or []) if isinstance(profile, dict)}
    clustering_evidence = {
        "cluster_count": clustering.get("cluster_count"),
        "window_count": clustering.get("window_count"),
        "selection_method": selection.get("method"),
        "forced_split": bool(selection.get("fallback_applied")),
        "unprofiled_speaker_count": len(turn_speakers - profile_speakers),
    }
    result = {
        **payload,
        "duration_ms": duration_ms,
        "segments": segments,
        "speech_regions": speech_regions,
        "speaker_turns": segmentation.get("speaker_turns", []),
        "summary": _summary(segments, emotions, events),
        "enrichment": {
            "schema_version": "sonovect/v2",
            "service_version": APP_VERSION,
            "vad": {"model": segmentation.get("vad_model", "fsmn-vad"),
                    "revision": segmentation.get("vad_revision"), "regions": "model"},
            "diarization": {
                "model": segmentation.get("diarization_model", "cam++"),
                "revision": segmentation.get("diarization_revision"),
                "scope": "request",
                "overlap_detection": bool(segmentation.get("overlap_detection")),
                "speaker_embeddings": "internal",
                "clustering": clustering_evidence,
                **({"identity_profiles": segmentation.get("speaker_profiles", [])} if include_speaker_identity else {}),
            },
            "acoustic_analysis": {"stage_payloads": {
                "events": {"payload": events_data, "error": events_error},
                "vocal": {"payload": moss, "error": acoustic_error},
                **({"measurements": {"payload": measurement_data, "error": measurement_error}} if measure else {})}},
            "lanes": {
                "speech": _lane_state(requested=True, error=speech_error, complete=speech_error is None),
                "acoustic": _lane_state(requested=full or voice or measure, error=acoustic_error or events_error or measurement_error, complete=(not full or bool(events_data and events_data.get("events_valid"))) and (not voice or bool(moss and moss.get("vocal_valid"))) and (not measure or bool(measurement_data and measurement_data.get("measurements_valid")))),
                "coverage": {"state": "completed", "duration_ms": duration_ms, "speech_ms": _speech_ms(segmentation)},
            },
        },
    }
    return result


async def _pipeline_once(parts: list[AudioPart], language: str, use_itn: bool, full: bool, speaker_identity: bool = False, context: str = "", voice: bool = False, measure_voice: bool = False) -> dict[str, Any]:
    if full and not SOUND_ENABLED:
        raise HTTPException(status_code=422, detail="sound_backend_not_configured")
    if voice and not VOICE_ENABLED:
        raise HTTPException(status_code=422, detail="voice_backend_not_configured")
    if measure_voice and not MEASUREMENTS_ENABLED:
        raise HTTPException(status_code=422, detail="measurements_backend_not_configured")
    if not parts:
        raise HTTPException(status_code=400, detail="No files provided")
    segmentation, _ = await asyncio.gather(
        _post_audio(SEGMENTATION_URL, "/analyze", parts, {}, SEGMENTATION_TIMEOUT),
        _release_sound_before_speech(),
    )
    # ASR windows follow VAD. Diarizer overlap must not duplicate audio or
    # force one voice onto all words in a window.
    planning = {"results": [{**s, "speaker_turns": []} if s.get("overlap_detection") else s
                            for s in _payloads(segmentation, len(parts))]}
    plan = build_request_plan(
        planning,
        file_count=len(parts),
        requested_language=language,
        target_ms=SEGMENT_TARGET_MS,
        hard_max_ms=SEGMENT_HARD_MAX_MS,
        merge_gap_ms=SEGMENT_MERGE_GAP_MS,
        boundary_silence_ms=SEGMENT_BOUNDARY_SILENCE_MS,
        padding_ms=SEGMENT_PADDING_MS,
    )
    speech_error = None
    try:
        qwen = await _post_audio(
            QWEN_URL,
            "/transcribe",
            parts,
            {"language": language, "use_itn": use_itn, "segment_plan": json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
             **({"context": context} if context else {})},
            QWEN_TIMEOUT,
        )
    except Exception as exc:
        if not full:
            raise
        speech_error = _safe_error(exc)
        qwen = {"results": [{"text": "", "raw_text": "", "segments": [], "words": []} for _ in parts]}
    events = moss = None
    events_error = acoustic_error = None
    measurement_data = None
    measurement_error = None
    if full:
        try:
            events = _strict_stage_payloads(await _post_audio(EVENTS_URL, "/analyze", parts, {}, EVENTS_TIMEOUT), len(parts))
        except Exception as exc:
            events_error = _safe_error(exc)
    if measure_voice:
        try:
            data = {"speech_context": json.dumps([
                {"speech_regions": s["speech_regions"]} for s in _payloads(segmentation, len(parts))])}
            measurement_data = _strict_stage_payloads(await _post_audio(
                MEASUREMENTS_URL, "/analyze", parts, data, MEASUREMENTS_TIMEOUT), len(parts))
        except Exception as exc:
            measurement_error = _safe_error(exc)
    if voice:
        # GPU handoff is needed only for explicitly requested MOSS, never AST.
        try:
            data = {}
            if VOICE_BACKEND == "moss":
                released = await _post_control(QWEN_URL, "/internal/unload")
                state = released.get("manager") or {}
                if released.get("status") != "unloaded" or state.get("resident", True) or state.get("busy", True):
                    raise RuntimeError("asr_unload_not_confirmed")
            else:
                data = {"speech_context": json.dumps([
                    {"speech_regions": s["speech_regions"]} for s in _payloads(segmentation, len(parts))])}
            moss = _strict_stage_payloads(await _post_audio(MOSS_URL, "/analyze", parts, data, MOSS_TIMEOUT), len(parts))
        except Exception as exc:
            acoustic_error = _safe_error(exc)
    segmentations = _payloads(segmentation, len(parts))
    qwens = _payloads(qwen, len(parts))
    mosses = moss if moss is not None else [None] * len(parts)
    event_values = events if events is not None else [None] * len(parts)
    outputs = [
        _compose(
            qwens[index], segmentations[index], mosses[index], speaker_identity,
            full=full, speech_error=speech_error, acoustic_error=acoustic_error,
            events_data=event_values[index], events_error=events_error, voice=voice,
            measure=measure_voice, measurement_data=measurement_data[index] if measurement_data else None,
            measurement_error=measurement_error,
        )
        for index in range(len(parts))
    ]
    return outputs[0] if len(outputs) == 1 else {"results": outputs}


async def _pipeline(parts: list[AudioPart], language: str, use_itn: bool, full: bool, speaker_identity: bool = False, context: str = "", voice: bool = False, measure_voice: bool = False) -> dict[str, Any]:
    # Qwen and MOSS share one GPU.  Per-worker locks are insufficient:
    # concurrent HTTP requests can otherwise interleave Qwen from one
    # request with MOSS from another and defeat the sequential unload contract.
    async with GPU_PIPELINE_LOCK:
        return await _pipeline_once(parts, language, use_itn, full, speaker_identity, context, voice, measure_voice)


async def _probe(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
            response = await client.get(f"{url}/health")
        response.raise_for_status()
        return {"reachable": True, "payload": response.json()}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


@app.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health")
async def health() -> dict[str, Any]:
    segmentation, qwen = await asyncio.gather(_probe(SEGMENTATION_URL), _probe(QWEN_URL))
    moss = await _probe(MOSS_URL) if VOICE_ENABLED else {"enabled": False, "reachable": False}
    events = await _probe(EVENTS_URL) if SOUND_ENABLED else {"enabled": False, "reachable": False}
    measurements = await _probe(MEASUREMENTS_URL) if MEASUREMENTS_ENABLED else {"enabled": False, "reachable": False}
    required = (segmentation, qwen)
    ready = all(item["reachable"] and item.get("payload", {}).get("status") == "ok" for item in required)
    return {
        "status": "ok" if ready else "degraded",
        "version": APP_VERSION,
        "service": "sonovect-speech-coordinator",
        "sound_analysis": SOUND_ENABLED, "voice_analysis": VOICE_ENABLED, "voice_backend": VOICE_BACKEND,
        "voice_measurements": MEASUREMENTS_ENABLED,
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "upstreams": {"segmentation": segmentation, "qwen3_asr": qwen, "vocal": moss, "moss_audio": moss, "events": events, "measurements": measurements},
    }


@app.get("/models")
async def models() -> dict[str, Any]:
    segmentation, asr = await asyncio.gather(_probe(SEGMENTATION_URL), _probe(QWEN_URL))
    acoustic = await _probe(MOSS_URL) if VOICE_ENABLED else {"reachable": False}
    events = await _probe(EVENTS_URL) if SOUND_ENABLED else {"reachable": False}
    measurement = await _probe(MEASUREMENTS_URL) if MEASUREMENTS_ENABLED else {"reachable": False}
    n = measurement.get("payload", {})
    e = events.get("payload", {})
    s, a, m = (item.get("payload", {}) for item in (segmentation, asr, acoustic))
    sm = s.get("models", {})
    return {
        "asr": a.get("model"),
        "forced_aligner": a.get("aligner"),
        "vad": sm.get("vad"),
        "speaker_diarization": sm.get("diarization_model", sm.get("speaker")),
        "acoustic_analysis": {"events": e.get("model"), "vocal": m.get("model"), "measurements": n.get("engine")},
        "revisions": {"asr": a.get("model_revision"), "forced_aligner": a.get("aligner_revision"),
                      "vad": sm.get("vad_revision"),
                      "speaker_diarization": sm.get("diarization_revision"), "acoustic_analysis": {"events": e.get("revision"), "vocal": m.get("revision")}},
        "reachable": {"segmentation": segmentation["reachable"], "asr": asr["reachable"], "vocal": acoustic["reachable"], "events": events["reachable"], "measurements": measurement["reachable"]},
    }


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return f"<h1>Sonovect {APP_VERSION}</h1><p><a href='/docs'>API docs</a></p>"


@app.post("/transcribe")
async def transcribe(
    files: Annotated[list[UploadFile], File(description="Audio files")],
    language: Annotated[str, Form()] = "auto",
    use_itn: Annotated[bool, Form()] = True,
    ban_emo_unk: Annotated[bool, Form()] = True,
    speaker_identity: Annotated[bool, Form()] = False,
    context: Annotated[str, Form()] = "",
) -> JSONResponse:
    del ban_emo_unk
    return JSONResponse(await _pipeline(await _read_parts(files), language, use_itn, False, speaker_identity, context))


@app.post("/transcribe/full")
async def transcribe_full(
    files: Annotated[list[UploadFile], File(description="Audio files")],
    language: Annotated[str, Form()] = "auto",
    use_itn: Annotated[bool, Form()] = True,
    ban_emo_unk: Annotated[bool, Form()] = True,
    speaker_identity: Annotated[bool, Form()] = False,
    context: Annotated[str, Form()] = "",
    analyze_sound: bool = Form(True),
    analyze_voice: bool = Form(False),
    measure_voice: bool = Form(False),
) -> JSONResponse:
    del ban_emo_unk
    return JSONResponse(await _pipeline(await _read_parts(files), language, use_itn, analyze_sound, speaker_identity, context, analyze_voice, measure_voice))
