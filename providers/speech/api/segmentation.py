from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


LANGUAGE_MAP = {
    "zh": "Chinese",
    "chinese": "Chinese",
    "yue": "Cantonese",
    "cantonese": "Cantonese",
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
}


@dataclass(frozen=True)
class AtomicRegion:
    start_ms: int
    end_ms: int
    speaker: Optional[str]
    language: str


def _language(value: Any, default: str = "auto") -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized and normalized not in {"auto", "unknown", "none"}:
            return LANGUAGE_MAP.get(normalized, value.strip())
    return default


def _valid_interval(item: Any, duration_ms: int) -> Optional[tuple[int, int]]:
    if not isinstance(item, dict):
        return None
    start = item.get("start_ms")
    end = item.get("end_ms")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    start_ms = max(0, round(float(start)))
    end_ms = round(float(end))
    if duration_ms > 0:
        end_ms = min(duration_ms, end_ms)
    if end_ms <= start_ms:
        return None
    return start_ms, end_ms


def _overlap(left: tuple[int, int], right: tuple[int, int]) -> int:
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def _segment_language(
    interval: tuple[int, int],
    segments: list[dict[str, Any]],
    fallback: str,
) -> str:
    best_language = fallback
    best_overlap = 0
    for segment in segments:
        candidate = _valid_interval(segment, 0)
        if candidate is None:
            continue
        overlap = _overlap(interval, candidate)
        if overlap > best_overlap:
            best_overlap = overlap
            best_language = _language(segment.get("language"), fallback)
    return best_language


def _payloads(payload: dict[str, Any], file_count: int) -> list[dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, list) and results and all(isinstance(item, dict) for item in results):
        values = list(results[:file_count])
    else:
        values = [payload]
    while len(values) < file_count:
        values.append({})
    return values


def _atomic_regions(payload: dict[str, Any], requested_language: str) -> tuple[list[AtomicRegion], int]:
    duration_value = payload.get("duration_ms")
    duration_ms = round(float(duration_value)) if isinstance(duration_value, (int, float)) else 0
    # An explicit empty VAD result means no speech. The full-audio
    # fallback below is only for providers that did not supply VAD at all.
    if payload.get("speech_regions") == []:
        return [], duration_ms
    explicit_language = requested_language.strip().lower() not in {"", "auto"}
    segments = [item for item in payload.get("segments", []) if isinstance(item, dict)]
    segment_language_values = [
        str(item.get("language", "")).strip().lower()
        for item in segments
        if str(item.get("language", "")).strip().lower() not in {"", "auto", "unknown", "none"}
    ]
    known_languages = {_language(value) for value in segment_language_values}
    has_unknown_segments = any(
        str(item.get("language", "")).strip().lower() in {"", "auto", "unknown", "none"}
        for item in segments
    )
    top_language = _language(payload.get("language"), "auto")
    speaker_turns_value = payload.get("speaker_turns")
    speaker_turn_count = len(speaker_turns_value) if isinstance(speaker_turns_value, list) else 0
    ambiguous_language = len(known_languages) > 1 or (
        top_language != "Chinese" and has_unknown_segments and speaker_turn_count > 1
    )
    fallback_language = (
        _language(requested_language)
        if explicit_language
        else "auto" if ambiguous_language else top_language
    )

    sources = [
        (payload.get("speaker_turns"), True),
        (payload.get("speech_regions"), False),
        (segments, True),
    ]
    regions: list[AtomicRegion] = []
    for items, include_speaker in sources:
        if not isinstance(items, list):
            continue
        candidate_regions: list[AtomicRegion] = []
        for item in items:
            interval = _valid_interval(item, duration_ms)
            if interval is None:
                continue
            if explicit_language:
                language = _language(requested_language)
            elif ambiguous_language:
                language = "auto"
            else:
                language = _segment_language(interval, segments, fallback_language)
            speaker = item.get("speaker") if include_speaker and isinstance(item.get("speaker"), str) else None
            candidate_regions.append(AtomicRegion(interval[0], interval[1], speaker, language))
        if candidate_regions:
            regions = candidate_regions
            break

    if not regions and duration_ms > 0:
        regions = [AtomicRegion(0, duration_ms, None, fallback_language)]

    regions.sort(key=lambda item: (item.start_ms, item.end_ms))
    return regions, duration_ms


def _merge_regions(
    regions: list[AtomicRegion],
    *,
    target_ms: int,
    hard_max_ms: int,
    merge_gap_ms: int,
    boundary_silence_ms: int,
) -> list[AtomicRegion]:
    if not regions:
        return []
    merged: list[AtomicRegion] = []
    current = regions[0]
    for region in regions[1:]:
        gap_ms = max(0, region.start_ms - current.end_ms)
        same_stream = region.speaker == current.speaker and region.language == current.language
        projected_ms = region.end_ms - current.start_ms
        soft_boundary = current.end_ms - current.start_ms >= target_ms and gap_ms >= boundary_silence_ms
        if same_stream and gap_ms <= merge_gap_ms and projected_ms <= hard_max_ms and not soft_boundary:
            current = AtomicRegion(current.start_ms, max(current.end_ms, region.end_ms), current.speaker, current.language)
            continue
        merged.append(current)
        current = region
    merged.append(current)
    return merged


def _split_long_regions(regions: list[AtomicRegion], hard_max_ms: int) -> list[AtomicRegion]:
    split: list[AtomicRegion] = []
    for region in regions:
        start_ms = region.start_ms
        while region.end_ms - start_ms > hard_max_ms:
            end_ms = start_ms + hard_max_ms
            split.append(AtomicRegion(start_ms, end_ms, region.speaker, region.language))
            start_ms = end_ms
        if region.end_ms > start_ms:
            split.append(AtomicRegion(start_ms, region.end_ms, region.speaker, region.language))
    return split


def _render_regions(regions: list[AtomicRegion], duration_ms: int, padding_ms: int) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for index, region in enumerate(regions):
        audio_start_ms = max(0, region.start_ms - padding_ms)
        audio_end_ms = min(duration_ms, region.end_ms + padding_ms) if duration_ms > 0 else region.end_ms + padding_ms
        if index > 0:
            previous = regions[index - 1]
            midpoint = (previous.end_ms + region.start_ms) // 2
            audio_start_ms = max(audio_start_ms, midpoint)
        if index + 1 < len(regions):
            following = regions[index + 1]
            midpoint = (region.end_ms + following.start_ms) // 2
            audio_end_ms = min(audio_end_ms, midpoint)
        audio_start_ms = min(audio_start_ms, region.start_ms)
        audio_end_ms = max(audio_end_ms, region.end_ms)
        rendered.append(
            {
                "start_ms": region.start_ms,
                "end_ms": region.end_ms,
                "audio_start_ms": audio_start_ms,
                "audio_end_ms": audio_end_ms,
                "speaker": region.speaker,
                "language": region.language,
            }
        )
    return rendered


def build_request_plan(
    segmentation_payload: dict[str, Any],
    *,
    file_count: int,
    requested_language: str,
    target_ms: int = 30_000,
    hard_max_ms: int = 90_000,
    merge_gap_ms: int = 3_000,
    boundary_silence_ms: int = 700,
    padding_ms: int = 1_000,
) -> dict[str, Any]:
    files: list[list[dict[str, Any]]] = []
    for payload in _payloads(segmentation_payload, file_count):
        atomic, duration_ms = _atomic_regions(payload, requested_language)
        merged = _merge_regions(
            atomic,
            target_ms=target_ms,
            hard_max_ms=hard_max_ms,
            merge_gap_ms=merge_gap_ms,
            boundary_silence_ms=boundary_silence_ms,
        )
        split = _split_long_regions(merged, hard_max_ms)
        files.append(_render_regions(split, duration_ms, padding_ms))
    return {
        "strategy": "speaker-continuity-chinese-first-v2",
        "target_ms": target_ms,
        "hard_max_ms": hard_max_ms,
        "merge_gap_ms": merge_gap_ms,
        "boundary_silence_ms": boundary_silence_ms,
        "padding_ms": padding_ms,
        "files": files,
    }
