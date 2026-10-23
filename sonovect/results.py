"""Speech-only results and separate acoustic analysis. No text decoration."""
from copy import deepcopy
from pydantic import ValidationError
from .models import Analysis, Observation, Quality, transcript_json


def native_result(value: dict, key: str, speakers: bool) -> dict:
    """Keep native speech fields unchanged; never synthesize missing alignment."""
    result = {name: deepcopy(value[name]) for name in ("text", "timestamp", "sentence_info") if name in value}
    result["key"] = key
    if not speakers:
        for sentence in result.get("sentence_info") or []:
            sentence.pop("spk", None)
    return transcript_json(result)


def speech_result(value: dict, key: str, speakers: bool) -> dict:
    """Adapt the bundled Qwen pipeline's millisecond segments to FunASR fields.

    Segments remain VAD/speaker-aligned segments, not invented punctuation
    sentences. Word spans come only from the aligner, never from interpolation.
    """
    result = {"key": key, "text": value.get("text", "")}
    sentences, labels = [], {}
    for segment in value.get("segments", []):
        if not segment.get("text"):
            continue
        sentence = {"text": segment["text"], "start": segment["start_ms"], "end": segment["end_ms"]}
        if "words" in segment:
            sentence["timestamp"] = [[word["start_ms"], word["end_ms"]] for word in segment["words"]]
        label = segment.get("speaker")
        if speakers and label is not None:
            if str(label) not in labels:
                labels[str(label)] = len(labels)
            sentence["spk"] = labels[str(label)]
        sentences.append(sentence)
    if "words" in value:
        result["timestamp"] = [[word["start_ms"], word["end_ms"]] for word in value["words"]]
    if "segments" in value:
        result["sentence_info"] = sentences
    return transcript_json(result)


def acoustic_result(value: dict, key: str, requested: bool, voice_requested: bool = False, measure_requested: bool = False) -> dict:
    """Read the current staged provider contract without altering speech artifacts."""
    from .models import AnalysisStage
    selected = [("events", requested), ("vocal", voice_requested), ("measurements", measure_requested)]
    try:
        return staged_acoustic_result(value, key, selected)
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError):
        any_requested = any(enabled for _, enabled in selected)
        return Analysis(key=key, status="failed" if any_requested else "not_requested",
            stages={name: AnalysisStage(status="failed" if enabled else "not_requested",
                    error=name+"_analysis_failed" if enabled else None) for name, enabled in selected},
            error="sound_analysis_failed" if any_requested else None,
            quality=Quality(warnings=["provider_analysis_invalid"])).model_dump(mode="json", exclude_none=True)


def staged_acoustic_result(value, key, selected):
    from .models import AnalysisStage, ModelIdentity, VoiceMeasurement
    coverage = value.get("enrichment", {}).get("lanes", {}).get("coverage", {})
    raw = value.get("enrichment", {}).get("acoustic_analysis", value)
    result = Analysis(key=key, status="not_requested", stages={}, engines={},
        quality=Quality(duration_ms=value.get("duration_ms"), speech_ms=coverage.get("speech_ms")))
    for name, requested in selected:
        if not requested:
            result.stages[name] = AnalysisStage(status="not_requested")
            continue
        stage = raw.get("stage_payloads", {}).get(name) or {}
        try:
            payload = stage.get("payload")
            valid_key = {"events": "events_valid", "vocal": "vocal_valid", "measurements": "measurements_valid"}[name]
            if stage.get("error") or not isinstance(payload, dict) or payload.get("parse_valid") is not True or payload.get(valid_key) is not True:
                raise ValueError("stage_incomplete")
            engine = ModelIdentity.model_validate(payload["engine"])
            fields = ["events"] if name == "events" else ["emotions", "voice"] if name == "vocal" else []
            observations = {field: [Observation.model_validate(item) for item in payload.get(field, [])
                if not (field == "events" and (item.get("kind") == "speech" or str(item.get("label", "")).casefold() in {"speech", "speaking", "talking"}))] for field in fields}
            numeric = [VoiceMeasurement.model_validate(item) for item in payload.get("measurements", [])] if name == "measurements" else []
            if result.quality.duration_ms is not None and any(item.end_ms > result.quality.duration_ms for item in numeric):
                raise ValueError("measurement_outside_media")
            for field, items in observations.items():
                if result.quality.duration_ms is not None and any(item.end_ms is not None and item.end_ms > result.quality.duration_ms for item in items):
                    raise ValueError("observation_outside_media")
                setattr(result, field, items)
            if name == "measurements":
                result.measurements = numeric
            result.engines[name] = engine
            result.stages[name] = AnalysisStage(status="completed")
            if name in {"vocal", "measurements"}:
                warnings = payload.get("warnings")
                for warning in ("vocal_presence_uncertain", "vocal_not_detected", "no_usable_speech", "emotion_uncertain"):
                    if isinstance(warnings, list) and warning in warnings and warning not in result.quality.warnings:result.quality.warnings.append(warning)
        except (KeyError, TypeError, ValueError, AttributeError):
            if name == "measurements":
                result.measurements = []
            for field in (["events"] if name == "events" else ["emotions", "voice"] if name == "vocal" else []):setattr(result, field, [])
            result.stages[name] = AnalysisStage(status="failed", error=name + "_analysis_failed")
    states = [x.status for x in result.stages.values() if x.status != "not_requested"]
    result.status = "not_requested" if not states else "completed" if all(x == "completed" for x in states) else "failed" if all(x == "failed" for x in states) else "partial"
    if result.status in {"failed", "partial"}:result.error = "sound_analysis_failed"
    if not result.engines:result.engines = None
    return result.model_dump(mode="json", exclude_none=True)


def as_text(results: list[dict]) -> str:
    return "\n".join(item["text"] for item in results)


def as_srt(results: list[dict]) -> str:
    if len(results) != 1:
        raise ValueError("SRT requires exactly one source; recordings have independent clocks")
    sentences = results[0].get("sentence_info")
    if sentences is None:
        raise ValueError("Sentence timing is unavailable")
    def stamp(ms):
        seconds, milli = divmod(ms, 1000)
        minutes, second = divmod(seconds, 60)
        hour, minute = divmod(minutes, 60)
        return f"{hour:02}:{minute:02}:{second:02},{milli:03}"
    return "\n\n".join(f"{i}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for i, s in enumerate(sentences, 1)) + ("\n" if sentences else "")
