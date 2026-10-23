"""Discoverable deployment choices, job options and retrieval formats."""
from .media import AUDIO_EXAMPLES, VIDEO_EXAMPLES
from .models import Options
from . import __version__


def describe(settings):
    sound = settings.sound_enabled and (settings.backend == "speech" or bool(settings.sound_url))
    voice = settings.voice_enabled and (settings.backend == "speech" or bool(settings.voice_url))
    measurements = settings.measurements_enabled and (settings.backend == "speech" or bool(settings.measurements_url))
    return {
        "version": __version__, "api_version": "v1", "backend": settings.backend, "transcript": "funasr-speech-v1",
        "analysis": "audio-analysis-v1", "speakers": True, "sound_analysis": sound, "voice_analysis": voice,
        "voice_backend": settings.voice_backend, "voice_measurements": measurements,
        "analysis_limits": {
            "events": {"kind": "closed-vocabulary-tags", "confidence": "uncalibrated", "requires_review": True},
            "vocal": {"maturity": "experimental", "presence": "existing-vad" if settings.voice_backend == "emotion2vec" else "model-gated",
                      "measurements": measurements, "chinese_quality_qualified": False, "requires_review": True},
            "measurements": {"kind": "signal-measurements", "model_weights": False,
                             "independent_of_vocal_backend": True, "requires_speech_intervals": True}},
        "timestamp_unit": "millisecond", "speaker_scope": "recording",
        "max_files": settings.max_files, "max_upload_bytes": settings.max_upload_bytes,
        "input_ttl_hours": settings.input_ttl_hours, "result_ttl_hours": settings.result_ttl_hours,
        "input": {"transport": "multipart-upload", "audio_examples": AUDIO_EXAMPLES,
                  "video_examples": VIDEO_EXAMPLES, "video_processing": "audio-track-only",
                  "audio_track_index": "zero-based", "timeline_origin": "container_start",
                  "channel_handling": "mono-downmix", "decoded_sample_rate": 16000,
                  "max_media_seconds": settings.max_media_seconds, "media_timeout_seconds": settings.media_timeout,
                  "codec_support": "depends-on-worker-ffmpeg-build"},
        "processing_routes": [
            {"id": "speech", "available": True, "options": {"speakers": True, "analyze_sound": False, "analyze_voice": False}},
            {"id": "speech-events", "available": sound, "options": {"speakers": True, "analyze_sound": True, "analyze_voice": False}},
            {"id": "speech-measurements", "available": measurements, "options": {"analyze_voice": False, "measure_voice": True}},
            {"id": "speech-events-vocal", "available": sound and voice, "options": {"speakers": True, "analyze_sound": True, "analyze_voice": True}}],
        "options_schema": Options.model_json_schema(),
        "default_options": Options().model_dump(),
        "option_semantics": {
            "language": "model-dependent-hint", "hotwords": "model-dependent-hint",
            "speakers_false": "omit-speaker-labels" if settings.backend == "speech" else "skip-speaker-model",
            "analyze_sound_false": "skip-event-inference", "analyze_voice_false": "skip-vocal-inference",
            "measure_voice_true": "independent-numeric-stage",
            "measure_voice_false": "skip-measurement-inference",
            "independent_acoustic_stages": True},
        "outputs": {"result": {"formats": ["json", "text", "srt"], "default": "json",
                               "srt_requires": "one-successful-source-with-sentence-timing"},
                    "analysis": {"formats": ["json"], "separate_from_transcript": True},
                    "export": {"artifacts": ["result.json", "analysis.json", "manifest.json"], "sha256": True}},
        "execution": {"layout": settings.layout, "mode": "queued-file-jobs", "streaming": False, "backend_selection": "deployment"},
    }
