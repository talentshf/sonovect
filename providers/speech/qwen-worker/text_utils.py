from __future__ import annotations

import re
from typing import Any


_UNIT = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
_LEADING_SEPARATOR = " \t\r\n，。！？；：,.!?;:、"


def _units(text: str) -> list[tuple[str, int]]:
    return [(match.group(0).lower(), match.end()) for match in _UNIT.finditer(text)]


def trim_rolling_context_prefix(
    previous_text: str,
    current_text: str,
    words: list[dict[str, Any]],
    *,
    minimum_overlap_characters: int = 6,
    maximum_overlap_characters: int = 240,
    maximum_removed_end_ms: int | None = None,
) -> tuple[str, list[dict[str, Any]], int]:
    previous_units = _units(previous_text)
    current_units = _units(current_text)
    maximum = min(len(previous_units), len(current_units), maximum_overlap_characters)
    overlap = 0
    for size in range(maximum, minimum_overlap_characters - 1, -1):
        if [item[0] for item in previous_units[-size:]] == [item[0] for item in current_units[:size]]:
            overlap = size
            break
    if overlap == 0:
        return current_text, words, 0

    raw_cut = current_units[overlap - 1][1]
    trimmed_text = current_text[raw_cut:].lstrip(_LEADING_SEPARATOR)
    consumed = 0
    word_cut = 0
    for index, word in enumerate(words):
        consumed += len(_units(str(word.get("text", ""))))
        word_cut = index + 1
        if consumed >= overlap:
            break
    if maximum_removed_end_ms is not None:
        removed_words = words[:word_cut]
        # Text equality cannot distinguish prompt echo from a real repetition.
        # Only discard a fully aligned prefix outside this chunk's owned span.
        if consumed != overlap or not removed_words or any(
            not isinstance(word.get("end_ms"), (int, float))
            or word["end_ms"] > maximum_removed_end_ms for word in removed_words
        ):
            return current_text, words, 0
    return trimmed_text, words[word_cut:], overlap
