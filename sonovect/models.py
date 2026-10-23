"""The public input and output contracts shared by all entry points."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Milliseconds = Annotated[int, Field(strict=True, ge=0)]


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    language: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w-]+$")
    speakers: bool = True
    analyze_sound: bool = Field(default=False, description="Request independent AST environment events")
    analyze_voice: bool = Field(default=False, description="Request the deployment-selected experimental vocal backend")
    measure_voice: bool = Field(default=False, description="Request independent weight-free pitch and energy measurements")
    hotwords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=200)
    audio_track: int = Field(default=0, ge=0, description="Zero-based audio stream index; applies to every source in the job")

    def wire(self):
        return self.model_dump()


def measurements_requested(options):
    return options.get("measure_voice", False)


class Sentence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str
    start: Milliseconds
    end: Milliseconds
    timestamp: list[tuple[Milliseconds, Milliseconds]] | None = None
    spk: Annotated[int, Field(strict=True, ge=0)] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("Sentence end precedes start")
        for start, end in self.timestamp or []:
            if end < start:
                raise ValueError("Timestamp end precedes start")
        return self


class Transcript(BaseModel):
    """FunASR AutoModel.generate speech-result subset, with optional fields."""
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str
    text: str
    timestamp: list[tuple[Milliseconds, Milliseconds]] | None = None
    sentence_info: list[Sentence] | None = None

    @model_validator(mode="after")
    def ordered(self):
        for start, end in self.timestamp or []:
            if end < start:
                raise ValueError("Timestamp end precedes start")
        return self


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str
    start_ms: Milliseconds | None = None
    end_ms: Milliseconds | None = None
    temporal_resolution: Literal["analysis-window", "model-interval", "unspecified"] = "unspecified"
    kind: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("Both time boundaries must be present or absent")
        if self.start_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Observation end precedes start")
        return self


class Quality(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    duration_ms: Milliseconds | None = None
    speech_ms: Milliseconds | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=128)


class AnalysisStage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["completed", "failed", "not_requested"]
    error: str | None = None


class VoiceMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["pitch", "relative-energy"]
    value: FiniteFloat | None = None
    unit: Literal["Hz", "dBFS"]
    method: Literal["pyin-50-600hz", "pcm-rms"]
    status: Literal["measured", "unavailable"]
    start_ms: Milliseconds
    end_ms: Milliseconds
    temporal_resolution: Literal["analysis-window"] = "analysis-window"

    @model_validator(mode="after")
    def consistent(self):
        expected = {"pitch": ("Hz", "pyin-50-600hz"), "relative-energy": ("dBFS", "pcm-rms")}
        if (self.unit, self.method) != expected[self.kind] or self.end_ms <= self.start_ms:
            raise ValueError("invalid_measurement_method_or_window")
        if (self.status == "measured") != (self.value is not None):
            raise ValueError("measurement_status_value_mismatch")
        if self.kind == "pitch" and self.value is not None and not 50 <= self.value <= 600:
            raise ValueError("pitch_outside_method_range")
        if self.kind == "relative-energy" and self.value is not None and self.value > 0:
            raise ValueError("energy_above_pcm_full_scale")
        return self


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["audio-analysis-v1"] = "audio-analysis-v1"
    key: str
    status: Literal["completed", "partial", "failed", "not_requested"]
    stages: dict[str, AnalysisStage] = Field(default_factory=dict)
    events: list[Observation] = Field(default_factory=list)
    emotions: list[Observation] = Field(default_factory=list)
    voice: list[Observation] = Field(default_factory=list)
    measurements: list[VoiceMeasurement] = Field(default_factory=list)
    quality: Quality = Field(default_factory=Quality)
    engines: dict[str, ModelIdentity] | None = None
    error: str | None = None


def transcript_json(value: dict) -> dict:
    # Validate JSON-shaped lists while enforcing strict integers and rejecting booleans.
    import json
    return Transcript.model_validate_json(json.dumps(value, allow_nan=False)).model_dump(mode="json", exclude_none=True)
