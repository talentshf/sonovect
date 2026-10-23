"""Fail early for misspelled enums and unsafe numeric deployment settings."""
import math
import os


def validate_environment():
    choices = {
        "QWEN_DTYPE": {"bfloat16", "float16", "float32"},
        "QWEN_ATTENTION_IMPLEMENTATION": {"auto", "sdpa", "eager"},
        "VAD_BACKEND": {"fsmn", "firered"}, "VAD_MODEL": {"fsmn-vad"}, "SPEAKER_MODEL": {"cam++"},
        "MOSS_DEBUG_RAW": {"true", "false"}, "MOSS_UNLOAD_AFTER_REQUEST": {"true", "false"},
        "SOUND_ENABLED": {"true", "false", "1", "0", "yes", "no"},
        "VOICE_ENABLED": {"true", "false", "1", "0", "yes", "no"},
        "MEASUREMENTS_ENABLED": {"true", "false", "1", "0", "yes", "no"},
        "VOICE_BACKEND": {"moss", "emotion2vec"},
        "SONOVECT_MODELS_OFFLINE": {"true", "false", "1", "0", "yes", "no"},
    }
    for key, allowed in choices.items():
        if key in os.environ and os.environ[key] not in allowed:
            raise ValueError("invalid_configuration:" + key)
    zero_ok = {"GPU_CAPACITY_WAIT_SECONDS", "QWEN_ROLLING_CONTEXT_CHARS", "MOSS_STRUCTURED_RETRIES",
               "SEGMENT_MERGE_GAP_MS", "SEGMENT_BOUNDARY_SILENCE_MS", "SEGMENT_PADDING_MS",
               "MIN_SPEAKER_PROFILE_DURATION_MS", "MIN_TEXT_DENSITY_PER_SPEECH_SECOND",
               "QWEN_MIN_FREE_GIB", "MOSS_MIN_FREE_GIB"}
    positive = {"MEASUREMENT_THREADS", "MEASUREMENT_WINDOW_SECONDS", "MEASUREMENTS_TIMEOUT_SECONDS", "VOCAL_THREADS", "VOCAL_WINDOW_SECONDS", "SOUND_EVENT_TOP_K", "SOUND_EVENT_WINDOW_SECONDS", "SOUND_EVENT_THREADS", "QWEN_GPU_BUDGET_MIB", "MOSS_GPU_BUDGET_MIB", "GPU_RESERVE_MIB",
                "QWEN_IDLE_UNLOAD_SECONDS", "MOSS_IDLE_UNLOAD_SECONDS", "QWEN_MAX_NEW_TOKENS",
                "QWEN_MAX_BATCH_SIZE", "QWEN_MAX_BATCH_AUDIO_SECONDS", "MOSS_MAX_NEW_TOKENS",
                "MOSS_MAX_CHUNK_SECONDS", "SEGMENT_TARGET_MS",
                "SEGMENT_HARD_MAX_MS", "SPEAKER_FALLBACK_MIN_WINDOWS", "SPEAKER_FALLBACK_COUNT",
                "EVENTS_TIMEOUT_SECONDS", "SEGMENTATION_TIMEOUT_SECONDS", "QWEN_TIMEOUT_SECONDS", "MOSS_TIMEOUT_SECONDS"}
    ranges = {"SPEAKER_MERGE_THRESHOLD": (0, 1), "SPEAKER_LOW_COHESION_COSINE": (-1, 1),
              "ACOUSTIC_ACTIVITY_DB": (-200, 0), "SOUND_EVENT_THRESHOLD": (0, 1)}
    for key in zero_ok | positive | ranges.keys():
        if key not in os.environ:
            continue
        try:
            v = float(os.environ[key])
            if not math.isfinite(v) or (key in positive and v <= 0) or (key in zero_ok and v < 0):
                raise ValueError()
            if key in ranges and not ranges[key][0] <= v <= ranges[key][1]:
                raise ValueError()
        except ValueError:
            raise ValueError("invalid_configuration:" + key) from None
    if int(os.getenv("GPU_RESERVE_MIB", "1024")) < 512:
        raise ValueError("gpu_reserve_must_be_at_least_512_mib")
    if int(os.getenv("SEGMENT_TARGET_MS", "30000")) > int(os.getenv("SEGMENT_HARD_MAX_MS", "90000")):
        raise ValueError("segment_target_exceeds_hard_max")
    if not 1 <= float(os.getenv("SOUND_EVENT_WINDOW_SECONDS", "10")) <= 10:
        raise ValueError("event_window_must_be_between_1_and_10_seconds")
    if not 1 <= float(os.getenv("VOCAL_WINDOW_SECONDS", "10")) <= 30:
        raise ValueError("vocal_window_must_be_between_1_and_30_seconds")
    if not 1 <= float(os.getenv("MEASUREMENT_WINDOW_SECONDS", "10")) <= 30:
        raise ValueError("measurement_window_must_be_between_1_and_30_seconds")
    for key, maximum in [("SOUND_EVENT_TOP_K", 10), ("SOUND_EVENT_THREADS", 32), ("VOCAL_THREADS", 32), ("MEASUREMENT_THREADS", 32)]:
        if key in os.environ and (not os.environ[key].isdigit() or not 1 <= int(os.environ[key]) <= maximum):
            raise ValueError("invalid_configuration:" + key)
