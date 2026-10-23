"""Bounded ASR microbatches preserve file boundaries and rolling context."""


def batch_ranges(audios, keys, *, size=1, seconds=60, rolling=False):
    if len(audios) != len(keys):
        raise ValueError("audio and context key counts must match")
    if not 1 <= size <= 4 or seconds <= 0:
        raise ValueError("invalid ASR batch limits")
    start = 0
    while start < len(audios):
        end, duration = start, 0.0
        file_key = keys[start].split(":", 1)[0]
        while end < len(audios) and end - start < (1 if rolling else size):
            waveform, sample_rate = audios[end]
            if sample_rate <= 0:
                raise ValueError("invalid audio sample rate")
            next_duration = len(waveform) / sample_rate
            if end > start and (keys[end].split(":", 1)[0] != file_key
                                or duration + next_duration > seconds):
                break
            duration += next_duration
            end += 1
        yield start, end
        start = end


def checked_results(results, expected):
    if len(results) != expected:
        raise RuntimeError("asr_result_count_mismatch")
    return results
