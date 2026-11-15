"""The public input and output contracts shared by all entry points."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Milliseconds = Annotated[int, Field(strict=True, ge=0)]


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    language: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w-]+$")
    transcribe: bool = True
    speakers: bool = False
    detect_speech: bool = False
    timestamps: Literal["none", "segment", "word"] = "none"
    context: str = Field(default="", max_length=4000, description="Recognition context, not an instruction")
    translate_to: str | None = Field(default=None, min_length=2, max_length=32, pattern=r"^[\w-]+$",
                                    exclude_if=lambda value: value is None)
    translation_context: str = Field(default="", max_length=4000, exclude_if=lambda value: not value)
    classify_audio: bool = Field(default=False, exclude_if=lambda value: not value)
    classify_top_k: int = Field(default=5, ge=1, le=527, exclude_if=lambda value: value == 5)
    alignment_text: str = Field(default="", max_length=12000, exclude_if=lambda value: not value)
    audio_question: str = Field(default="", max_length=12000, exclude_if=lambda value: not value)
    analyze_sound: bool = Field(default=False, description="Request independent AST environment events")
    analyze_voice: bool = Field(default=False, description="Request the deployment-selected experimental vocal backend")
    measure_voice: bool = Field(default=False, description="Request independent weight-free pitch and energy measurements")
    hotwords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=200)
    channel_mode: Literal["mix", "independent"] = Field(default="mix", exclude_if=lambda value: value == "mix")
    audio_track: int = Field(default=0, ge=0, description="Zero-based audio stream index; applies to every source in the job")

    @model_validator(mode="after")
    def selected_processing(self):
        if self.alignment_text and (self.transcribe or not self.language):
            raise ValueError("alignment_requires_text_language_and_no_transcription")
        if self.classify_top_k != 5 and not self.classify_audio:
            raise ValueError("classify_top_k_without_classification")
        if self.translation_context and not self.translate_to:
            raise ValueError("translation_context_without_translation")
        if not self.transcribe:
            if self.timestamps != "none" or self.context or self.hotwords or self.translate_to:
                raise ValueError("transcription_options_without_transcription")
            if not (self.speakers or self.detect_speech or self.analyze_sound or self.analyze_voice or self.measure_voice or self.classify_audio or self.audio_question or self.alignment_text):
                raise ValueError("no_processing_requested")
        return self

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


class AudioInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_ms: Milliseconds
    end_ms: Milliseconds

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms < self.start_ms:
            raise ValueError("invalid_audio_interval")
        return self


class SpeakerInterval(AudioInterval):
    speaker: str | None = None


class ClassScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str
    score: FiniteFloat = Field(ge=0,le=1)


class AlignedWord(BaseModel):
    model_config = ConfigDict(extra="forbid",strict=True)
    text: str
    start_ms: Milliseconds
    end_ms: Milliseconds


class Alignment(BaseModel):
    model_config = ConfigDict(extra="forbid",strict=True)
    text: str
    text_source: Literal["user"]
    language: str
    words: list[AlignedWord]
    engine: ModelIdentity


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scores: list[ClassScore]
    engine: ModelIdentity
    aggregation: str
    window_seconds: FiniteFloat


class AudioAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str
    model: str
    engine: ModelIdentity | None = None
    identity_source: Literal["operator-configuration","engine-response"]
    finish_reason: Literal["stop","length"] = "stop"
    usage: dict[str,int] | None = None
    input: Literal["audio"]
    requires_review: bool


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["audio-analysis-v1"] = "audio-analysis-v1"
    key: str
    status: Literal["completed", "partial", "failed", "not_requested"]
    stages: dict[str, AnalysisStage] = Field(default_factory=dict)
    alignment: Alignment | None = None
    classification: Classification | None = None
    understanding: AudioAnswer | None = None
    events: list[Observation] = Field(default_factory=list)
    emotions: list[Observation] = Field(default_factory=list)
    voice: list[Observation] = Field(default_factory=list)
    measurements: list[VoiceMeasurement] = Field(default_factory=list)
    speech_regions: list[AudioInterval] = Field(default_factory=list)
    speaker_turns: list[SpeakerInterval] = Field(default_factory=list)
    quality: Quality = Field(default_factory=Quality)
    engines: dict[str, ModelIdentity] | None = None
    error: str | None = None


def transcript_json(value: dict) -> dict:
    # Validate JSON-shaped lists while enforcing strict integers and rejecting booleans.
    import json
    return Transcript.model_validate_json(json.dumps(value, allow_nan=False)).model_dump(mode="json", exclude_none=True)
