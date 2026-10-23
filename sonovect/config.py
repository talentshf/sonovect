"""Operator configuration; no machine-specific discovery or credentials."""
from dataclasses import dataclass, field
from pathlib import Path
import os
import math
from .auth import token_from_env


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path("./data/jobs"))
    token: str = ""
    backend: str = "funasr"
    layout: str = "compact"
    provider_url: str = "http://speech-provider:8080"
    provider_timeout: float = 7200
    max_upload_bytes: int = 256 * 1024**2
    max_files: int = 16
    max_media_seconds: float = 7200
    media_timeout: float = 300
    input_ttl_hours: float = 24
    result_ttl_hours: float = 168
    lease_seconds: float = 120
    poll_seconds: float = 0.1
    worker_stale_seconds: float = 45
    model: str = "paraformer-zh"
    model_revision: str = "v2.0.4"
    device: str = "cpu"
    sound_url: str = ""
    sound_enabled: bool = True
    voice_enabled: bool = False
    voice_url: str = ""
    voice_backend: str = "moss"
    measurements_enabled: bool = False
    measurements_url: str = ""

    def __post_init__(self):
        if not self.token or self.token in {"change-me", "REPLACE_ME", "development-token"}:
            raise ValueError("Set SONOVECT_TOKEN to a non-placeholder secret")
        if self.layout not in {"compact", "distributed", "external"}:
            raise ValueError("SONOVECT_LAYOUT must be compact, distributed or external")
        if self.backend not in {"funasr", "speech"}:
            raise ValueError("SONOVECT_BACKEND must be funasr or speech")
        if self.voice_backend not in {"moss", "emotion2vec"}:
            raise ValueError("SONOVECT_VOICE_BACKEND must be moss or emotion2vec")
        limits = (self.max_upload_bytes, self.max_files, self.input_ttl_hours,
               self.result_ttl_hours, self.lease_seconds, self.poll_seconds, self.provider_timeout,
               self.worker_stale_seconds, self.max_media_seconds, self.media_timeout)
        if any(not math.isfinite(value) or value <= 0 for value in limits):
            raise ValueError("Limits, retention and timeout values must be positive")

    @classmethod
    def from_env(cls):
        p = "SONOVECT_"
        return cls(
            data_dir=Path(os.getenv(p + "DATA_DIR", "./data/jobs")).expanduser(),
            token=token_from_env(),
            backend=os.getenv(p + "BACKEND", "funasr"),
            layout=os.getenv(p + "LAYOUT", "compact"),
            provider_url=os.getenv(p + "PROVIDER_URL", "http://speech-provider:8080").rstrip("/"),
            provider_timeout=float(os.getenv(p + "PROVIDER_TIMEOUT", "7200")),
            max_upload_bytes=int(os.getenv(p + "MAX_UPLOAD_BYTES", str(256 * 1024**2))),
            max_files=int(os.getenv(p + "MAX_FILES", "16")),
            max_media_seconds=float(os.getenv(p + "MAX_MEDIA_SECONDS", "7200")),
            media_timeout=float(os.getenv(p + "MEDIA_TIMEOUT", "300")),
            input_ttl_hours=float(os.getenv(p + "INPUT_TTL_HOURS", "24")),
            result_ttl_hours=float(os.getenv(p + "RESULT_TTL_HOURS", "168")),
            lease_seconds=float(os.getenv(p + "LEASE_SECONDS", "120")),
            poll_seconds=float(os.getenv(p + "POLL_SECONDS", "0.1")),
            worker_stale_seconds=float(os.getenv(p + "WORKER_STALE_SECONDS", "45")),
            model=os.getenv(p + "MODEL", "paraformer-zh"),
            model_revision=os.getenv(p + "MODEL_REVISION", "v2.0.4"),
            device=os.getenv(p + "DEVICE", "cpu"),
            voice_url=os.getenv(p + "VOICE_URL", "").rstrip("/"),
            voice_enabled=os.getenv(p + "VOICE_ENABLED", "false").lower() in {"true", "1", "yes"},
            voice_backend=os.getenv(p + "VOICE_BACKEND", "moss"),
            measurements_enabled=os.getenv(p + "MEASUREMENTS_ENABLED", "false").lower() in {"true", "1", "yes"},
            measurements_url=os.getenv(p + "MEASUREMENTS_URL", "").rstrip("/"),
            sound_url=os.getenv(p + "SOUND_URL", "").rstrip("/"),
            sound_enabled=os.getenv(p + "SOUND_ENABLED", "true").lower() in {"true", "1", "yes"},
        )
