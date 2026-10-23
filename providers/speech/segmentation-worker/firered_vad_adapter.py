"""Pinned CPU FireRedVAD backend; empty speech is an explicit result."""

import hashlib
import math
from pathlib import Path


MODEL_ID = "FireRedTeam/FireRedVAD"
MODEL_SHA256 = "63f4fb1b00a6b8607c118dd48efc18d5e40d67d99b7bf9aa7a8d61540cf23d71"
CMVN_SHA256 = "c87f6f13edf0f0ec7535ddfc9cc3387d9268cb234b70182d566c5e2edf3ca473"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model(root: str | Path) -> Path:
    path = Path(root)
    for name, expected in (("model.pth.tar", MODEL_SHA256), ("cmvn.ark", CMVN_SHA256)):
        if _sha256(path / name) != expected:
            raise RuntimeError("firered_vad_model_hash_mismatch:" + name)
    return path


def load_model(root: str | Path):
    from fireredvad.vad import FireRedVad, FireRedVadConfig

    return FireRedVad.from_pretrained(str(verify_model(root)), FireRedVadConfig(use_gpu=False))


def speech_regions(result: dict, duration_ms: int) -> list[dict]:
    timestamps = result.get("timestamps")
    if not isinstance(timestamps, list):
        raise ValueError("firered_vad_timestamps_invalid")
    regions = []
    for pair in timestamps:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("firered_vad_timestamps_invalid")
        start_s, end_s = float(pair[0]), float(pair[1])
        if not math.isfinite(start_s) or not math.isfinite(end_s) or end_s <= start_s:
            raise ValueError("firered_vad_timestamps_invalid")
        start = max(0, min(duration_ms, round(start_s * 1000)))
        end = max(0, min(duration_ms, round(end_s * 1000)))
        if end > start:
            regions.append({"start_ms": start, "end_ms": end, "confidence": None})
    regions.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    return regions
