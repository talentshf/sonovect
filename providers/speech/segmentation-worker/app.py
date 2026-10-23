from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import librosa
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from funasr import AutoModel
from funasr.models.campplus.cluster_backend import ClusterBackend, SpectralCluster
from funasr.models.campplus.utils import postprocess, sv_chunk
from speaker_policy import should_apply_low_cohesion_fallback
from spectral import spectral_embeddings
from firered_vad_adapter import MODEL_ID as FIRERED_VAD_MODEL, MODEL_SHA256 as FIRERED_VAD_REVISION
from firered_vad_adapter import load_model as load_firered_vad, speech_regions as firered_speech_regions
from model_lock import resolve_pinned_model
from typing_extensions import Annotated


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("speech-segmentation-worker")

from sonovect_version import VERSION as APP_VERSION
from runtime_config import validate_environment
validate_environment()
DIARIZATION_BACKEND = "campplus"
SAMPLE_RATE = 16_000
VAD_MODEL = os.getenv("VAD_MODEL", "fsmn-vad")
VAD_BACKEND = os.getenv("VAD_BACKEND", "fsmn")
if VAD_BACKEND not in {"fsmn", "firered"}:
    raise RuntimeError("vad_backend_invalid")
SPEAKER_MODEL = os.getenv("SPEAKER_MODEL", "cam++")
MODEL_DEVICE = os.getenv("SEGMENTATION_DEVICE", "cpu")
SPEAKER_MERGE_THRESHOLD = float(os.getenv("SPEAKER_MERGE_THRESHOLD", "0.78"))
SPEAKER_LOW_COHESION_COSINE = float(os.getenv("SPEAKER_LOW_COHESION_COSINE", "0.45"))
SPEAKER_FALLBACK_MIN_WINDOWS = int(os.getenv("SPEAKER_FALLBACK_MIN_WINDOWS", "20"))
SPEAKER_FALLBACK_COUNT = int(os.getenv("SPEAKER_FALLBACK_COUNT", "2"))
MIN_SPEAKER_PROFILE_DURATION_MS = int(os.getenv("MIN_SPEAKER_PROFILE_DURATION_MS", "5000"))


class BoundedSpectralCluster(SpectralCluster):
    def get_spec_embs(self, laplacian, k_oracle=None):
        return spectral_embeddings(laplacian, self.min_num_spks, self.max_num_spks, k_oracle)


class Models:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vad: Any = None
        self._speaker: Any = None
        self._cluster: Any = None
        self._error: str | None = None

    def load(self) -> None:
        with self._lock:
            if self._vad is not None and self._speaker is not None and self._cluster is not None:
                return
            try:
                if VAD_BACKEND == "firered":
                    from sonovect_assets import resolve
                    root = os.getenv("FIRERED_VAD_ROOT") or str(Path(resolve("firered")) / "VAD")
                    self._vad = load_firered_vad(root)
                else:
                    self._vad = AutoModel(
                        model=resolve_pinned_model(VAD_MODEL, os.getenv("MODELSCOPE_CACHE", "/models")),
                        device=MODEL_DEVICE,
                        disable_update=True,
                        vad_kwargs={"max_single_segment_time": 30_000},
                    )
                self._speaker = AutoModel(
                    model=resolve_pinned_model(SPEAKER_MODEL, os.getenv("MODELSCOPE_CACHE", "/models")),
                    device=MODEL_DEVICE,
                    disable_update=True,
                )
                self._cluster = ClusterBackend(merge_thr=SPEAKER_MERGE_THRESHOLD).to(MODEL_DEVICE)
                previous = self._cluster.spectral_cluster
                self._cluster.spectral_cluster = BoundedSpectralCluster(previous.min_num_spks, previous.max_num_spks, previous.pval)
                self._error = None
            except Exception as exc:
                self._vad = None
                self._speaker = None
                self._cluster = None
                self._error = str(exc)
                raise

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self._vad is not None and self._speaker is not None and self._cluster is not None,
            "last_load_error": self._error,
        }

    def analyze(self, path: Path) -> dict[str, Any]:
        # A disconnected HTTP caller must not start concurrent inference on these models.
        with self._lock:
            return self._analyze(path)

    def speech_regions(self, waveform: np.ndarray) -> list[dict[str, Any]]:
        """Shared selected-VAD path for inference and offline diagnostics."""
        duration_ms = round(len(waveform) * 1000 / SAMPLE_RATE)
        if VAD_BACKEND == "firered":
            # The provider may upload encoded audio with a .wav filename.
            # Reuse the decoded 16 kHz signal instead of asking soundfile to
            # infer a codec from that temporary suffix.
            pcm16 = (np.clip(waveform, -1.0, 1.0) * 32767).astype(np.int16)
            vad_result, _ = self._vad.detect(pcm16)
            speech_regions = firered_speech_regions(vad_result, duration_ms)
        else:
            vad_result = self._vad.generate(input=waveform, fs=SAMPLE_RATE)
            raw_regions = []
            if vad_result and isinstance(vad_result[0], dict):
                raw_regions = vad_result[0].get("value") or []
            speech_regions = _speech_regions(raw_regions, duration_ms)
        return speech_regions

    def _analyze(self, path: Path) -> dict[str, Any]:
        self.load()
        started = time.monotonic()
        waveform, _ = librosa.load(path, sr=SAMPLE_RATE, mono=True)
        duration_ms = round(len(waveform) * 1000 / SAMPLE_RATE)
        decoded = time.monotonic()
        speech_regions = self.speech_regions(waveform)
        vad_done = time.monotonic()
        segments = sv_chunk([
            [
                float(region["start_ms"]) / 1000,
                float(region["end_ms"]) / 1000,
                waveform[round(int(region["start_ms"]) * SAMPLE_RATE / 1000):round(int(region["end_ms"]) * SAMPLE_RATE / 1000)],
            ]
            for region in speech_regions
        ], fs=SAMPLE_RATE)
        embeddings = [self._embedding(waveform, round(item[0] * 1000), round(item[1] * 1000)) for item in segments]
        embeddings_done = time.monotonic()
        if embeddings:
            matrix = np.stack(embeddings)
            labels, selection = _cluster_speakers(matrix, self._cluster)
            distributed, centers = postprocess(segments, None, labels, matrix, return_spk_center=True)
        else:
            distributed, centers = [], np.empty((0, 0), dtype=np.float32)
            selection = {
                "method": "empty",
                "spectral_cluster_count": 0,
                "cohesion_median": None,
                "fallback_applied": False,
            }
        logger.info("segmentation duration_ms=%s windows=%s decode_s=%.2f vad_s=%.2f embedding_s=%.2f clustering_s=%.2f", duration_ms, len(segments), decoded-started, vad_done-decoded, embeddings_done-vad_done, time.monotonic()-embeddings_done)
        speaker_turns = _speaker_turns(distributed)
        clustering = {
            "state": "ok" if embeddings else "empty",
            "backend": "funasr_cluster_backend",
            "cluster_count": len(centers),
            "window_count": len(segments),
            "merge_threshold": SPEAKER_MERGE_THRESHOLD,
            "selection": selection,
        }
        return {
            "duration_ms": duration_ms,
            "vad_model": FIRERED_VAD_MODEL if VAD_BACKEND == "firered" else VAD_MODEL,
            "vad_revision": FIRERED_VAD_REVISION if VAD_BACKEND == "firered" else None,
            "speech_regions": speech_regions,
            "speaker_turns": speaker_turns,
            "speaker_profiles": _speaker_profiles(speaker_turns, centers),
            "speaker_clustering": clustering,
        }


    def _embedding(self, waveform: np.ndarray, start_ms: int, end_ms: int) -> np.ndarray:
        start = max(0, round(start_ms * SAMPLE_RATE / 1000))
        end = min(len(waveform), round(end_ms * SAMPLE_RATE / 1000))
        chunk = waveform[start:end]
        if chunk.size < SAMPLE_RATE // 4:
            chunk = np.pad(chunk, (0, max(0, SAMPLE_RATE // 4 - chunk.size)))
        result = self._speaker.generate(input=[chunk], fs=SAMPLE_RATE)
        if not result or "spk_embedding" not in result[0]:
            raise RuntimeError("CAM++ returned no speaker embedding")
        value = result[0]["spk_embedding"]
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        vector = np.asarray(value, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector


def _speech_regions(raw: Any, duration_ms: int) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for value in raw:
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                continue
            start_ms = max(0, round(float(value[0])))
            end_ms = min(duration_ms, round(float(value[1])))
            if end_ms > start_ms:
                regions.append({"start_ms": start_ms, "end_ms": end_ms, "confidence": None})
    return regions


def _window_cosine_median(matrix: np.ndarray) -> float | None:
    if matrix.shape[0] < 2:
        return None
    normalized = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    affinity = normalized @ normalized.T
    pairwise = affinity[np.triu_indices_from(affinity, k=1)]
    return float(np.median(pairwise)) if pairwise.size else None


def _cluster_speakers(matrix: np.ndarray, backend: ClusterBackend) -> tuple[np.ndarray, dict[str, Any]]:
    if matrix.shape[0] < 20:
        labels = np.zeros(matrix.shape[0], dtype=int)
        return labels, {
            "method": "funasr_short_sample_guard",
            "spectral_cluster_count": 1 if matrix.shape[0] else 0,
            "cohesion_median": _window_cosine_median(matrix),
            "fallback_applied": False,
        }

    raw_labels = np.asarray(backend.spectral_cluster(matrix), dtype=int)
    raw_cluster_count = int(raw_labels.max()) + 1 if raw_labels.size else 0
    cohesion_median = _window_cosine_median(matrix)
    fallback_applied = should_apply_low_cohesion_fallback(
        window_count=matrix.shape[0],
        raw_cluster_count=raw_cluster_count,
        cohesion_median=cohesion_median,
        minimum_windows=SPEAKER_FALLBACK_MIN_WINDOWS,
        maximum_cohesion=SPEAKER_LOW_COHESION_COSINE,
    )
    if fallback_applied:
        raw_labels = np.asarray(
            backend.spectral_cluster(matrix, oracle_num=SPEAKER_FALLBACK_COUNT),
            dtype=int,
        )
    labels = np.asarray(backend.merge_by_cos(raw_labels.copy(), matrix, SPEAKER_MERGE_THRESHOLD), dtype=int)
    return labels, {
        "method": "low_cohesion_fallback_v1" if fallback_applied else "funasr_spectral_v1",
        "spectral_cluster_count": raw_cluster_count,
        "cohesion_median": cohesion_median,
        "fallback_applied": fallback_applied,
        "fallback_count": SPEAKER_FALLBACK_COUNT if fallback_applied else None,
    }


def _speaker_turns(distributed: list[list[Any]]) -> list[dict[str, Any]]:
    return [
        {
            "start_ms": round(float(start) * 1000),
            "end_ms": round(float(end) * 1000),
            "speaker": f"SPK_{int(label)}",
            "overlap": False,
            "confidence": None,
        }
        for start, end, label in distributed
    ]


def _speaker_profiles(
    turns: list[dict[str, Any]],
    centers: np.ndarray,
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for label, center in enumerate(centers):
        speaker = f"SPK_{label}"
        duration_ms = sum(
            int(turn["end_ms"]) - int(turn["start_ms"])
            for turn in turns if turn["speaker"] == speaker
        )
        if duration_ms < MIN_SPEAKER_PROFILE_DURATION_MS:
            continue
        centroid = np.asarray(center, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(centroid))
        if norm > 0:
            centroid = centroid / norm
        profiles.append({
            "speaker": speaker,
            "model": SPEAKER_MODEL,
            "window_count": sum(1 for turn in turns if turn["speaker"] == speaker),
            "sample_duration_ms": duration_ms,
            "embedding": [round(float(value), 7) for value in centroid.tolist()],
        })
    return profiles


models = Models()
app = FastAPI(title="Sonovect segmentation", version=APP_VERSION)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok" if models.status()["last_load_error"] is None else "degraded",
        "version": APP_VERSION,
        "models": {"vad": FIRERED_VAD_MODEL if VAD_BACKEND == "firered" else VAD_MODEL,
                   "vad_revision": FIRERED_VAD_REVISION if VAD_BACKEND == "firered" else None,
                   "speaker": SPEAKER_MODEL, "diarization": DIARIZATION_BACKEND,
                   "diarization_model": SPEAKER_MODEL,
                   "diarization_revision": None},
        "manager": models.status(),
    }


@app.post("/internal/load")
async def load_models() -> dict[str, Any]:
    try:
        await asyncio.to_thread(models.load)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "loaded", "manager": models.status()}


@app.post("/analyze")
async def analyze(
    files: Annotated[list[UploadFile], File(description="Audio files")],
) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    temp_paths: list[Path] = []
    try:
        for upload in files:
            suffix = Path(upload.filename or "audio.wav").suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(await upload.read())
                path = Path(handle.name)
            temp_paths.append(path)
            outputs.append(await asyncio.to_thread(models.analyze, path))
    except Exception as exc:
        logger.exception("segmentation_failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)
    return outputs[0] if len(outputs) == 1 else {"results": outputs}
