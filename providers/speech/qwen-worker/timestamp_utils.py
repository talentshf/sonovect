from __future__ import annotations

from typing import Any


def validated_word_spans(words: list[dict[str, Any]], duration_ms: int) -> list[dict[str, Any]]:
    """Keep real alignment unchanged, including genuine zero-duration spans.

    Invalid or unordered alignment makes this chunk's word timing unavailable;
    its transcript survives. Never clamp boundaries or add invented durations.
    """
    previous_start_ms = 0
    for word in words:
        start, end = word.get("start_ms"), word.get("end_ms")
        if (type(start) is not int or type(end) is not int or
                not previous_start_ms <= start <= end <= duration_ms):
            return []
        previous_start_ms = start
    return [dict(word) for word in words]


def offset_word_spans(words: list[dict[str, Any]], offset_ms: int) -> list[dict[str, Any]]:
    return [
        {
            **word,
            "start_ms": int(word["start_ms"]) + offset_ms,
            "end_ms": int(word["end_ms"]) + offset_ms,
        }
        for word in words
    ]
