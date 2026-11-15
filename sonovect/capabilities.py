"""Discoverable deployment choices, job options and retrieval formats."""
from .media import AUDIO_EXAMPLES, VIDEO_EXAMPLES
from .models import Options
from .languages import QWEN_LANGUAGES
from . import __version__


def describe(settings):
    from .realtime import capability
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
                  "channel_handling": ["mix", "independent"], "max_independent_channels":8, "decoded_sample_rate": 16000,
                  "max_media_seconds": settings.source_seconds_limit, "media_timeout_seconds": settings.media_timeout,
                  "codec_support": "depends-on-worker-ffmpeg-build"},
        "processing_routes": [
            {"id":"translation","available":bool(settings.translation_url),"options":{"translate_to":"en"}},
            {"id":"classification","available":sound and bool(settings.sound_url),"options":{"transcribe":False,"classify_audio":True}},
            {"id":"audio-question","available":bool(settings.understanding_url),"options":{"transcribe":False},"required_options":["audio_question"]},
            {"id":"supplied-text-alignment","available":settings.backend=="speech","options":{"transcribe":False},"required_options":["alignment_text","language"]},
            {"id":"independent-channels","available":True,"options":{"channel_mode":"independent"}},
            {"id": "speech", "available": True, "options": {"speakers": False, "timestamps": "none", "analyze_sound": False, "analyze_voice": False}},
            {"id": "speech-timed", "available": settings.backend != "vibevoice", "options": {"timestamps": "word"}},
            {"id": "speech-diarized", "available": True, "options": {"speakers": True}},
            {"id": "analysis-only", "available": settings.backend == "speech" and sound, "options": {"transcribe": False, "analyze_sound": True}},
            {"id": "speech-activity", "available": settings.backend == "speech", "options": {"transcribe": False, "detect_speech": True}},
            {"id": "speech-events", "available": sound, "options": {"speakers": True, "analyze_sound": True, "analyze_voice": False}},
            {"id": "speech-measurements", "available": measurements, "options": {"analyze_voice": False, "measure_voice": True}},
            {"id": "speech-events-vocal", "available": sound and voice, "options": {"speakers": True, "analyze_sound": True, "analyze_voice": True}}],
        "options_schema": Options.model_json_schema(),
        "default_options": Options().model_dump(),
        "option_semantics": {
            "language": "model-dependent-hint", "hotwords": "model-dependent-hint",
            "speakers_false": "omit-intrinsic-speaker-labels" if settings.backend == "vibevoice" else "skip-speaker-model",
            "timestamps_none": "skip-forced-alignment-unless-speakers-require-it",
            "analyze_sound_false": "skip-event-inference", "analyze_voice_false": "skip-vocal-inference",
            "measure_voice_true": "independent-numeric-stage",
            "measure_voice_false": "skip-measurement-inference",
            "independent_acoustic_stages": True},
        "outputs": {"result": {"formats": ["json", "text", "srt"], "default": "json",
                               "srt_requires": "one-successful-source-with-sentence-timing"},
                    "analysis": {"formats": ["json"], "separate_from_transcript": True},
                    "export": {"artifacts": ["result.json", "analysis.json", "manifest.json"], "sha256": True}},
        "realtime": capability(settings),
        "speech_limits": {"languages":list(QWEN_LANGUAGES) if settings.backend=="speech" else (["zh"] if settings.model=="paraformer-zh" else []),
                          "language_quality":"upstream-support; deployment-tests-are-separate", "word_timestamps": settings.backend != "vibevoice",
                          "max_media_seconds": settings.source_seconds_limit,
                          "alignment_languages":["zh","en","yue","fr","de","it","ja","ko","pt","ru","es"] if settings.backend=="speech" else None},
        "execution": {"layout": settings.layout, "mode": "jobs-and-live" if settings.realtime_enabled else "queued-file-jobs", "streaming": settings.backend=="speech" or settings.realtime_enabled, "max_queued":settings.max_queued,
                      "file_streaming": settings.backend == "speech", "realtime_input": settings.realtime_enabled, "backend_selection": "deployment",
                      "source_checkpoints": True, "retry_preserves_completed_stages": settings.backend == "speech",
                      "events": "/v1/jobs/{job_id}/events", "completion_callback": bool(settings.callback_hosts)},
        "standard_transcription": {"path": "/v1/audio/transcriptions", "model": settings.transcription_model,
                                   "formats": ["json", "text", "srt", "vtt", "diarized_json"] + (["verbose_json:word"] if settings.backend == "speech" else []),
                                   "file_streaming": settings.backend == "speech", "stream_semantics": "completed-asr-chunks; final-transcript-matches-stored-result",
                                   "sync_timeout_seconds": settings.sync_timeout},
        "alignment": {"configured":settings.backend=="speech","job_option":"alignment_text","max_seconds":90,"text_source":"user","retranscription":False},
        "protocols": {"openai_file":"/v1/audio/transcriptions","openai_realtime":"/v1/realtime?intent=transcription",
                      "deepgram":{"path":"/v1/listen","file_input":"uploaded-bytes","live":"linear16-mono-manual-finalize","confidence":"unavailable-omitted"},
                      "funasr":{"path":"/v1/funasr","modes":["offline"],"formats":["pcm"],"weighted_hotwords":False},
                      "wyoming":{"optional_bridge":True,"library":"wyoming==1.11.0","authentication":"trusted-network"}},
        "audio_classification": {"configured":settings.sound_enabled and bool(settings.sound_url), "path":"/models/ast-audioset",
                                 "aggregation":"duration-weighted-window-mean-sigmoid", "speech_labels_included":True},
        "audio_understanding": {"configured":bool(settings.understanding_url),"path":"/v1/chat/completions",
                                "model":settings.understanding_model or None,"input":"audio","output":"text",
                                "max_seconds":settings.understanding_max_seconds,"requires_review":True},
        "translation": {"configured": bool(settings.translation_url), "path": "/v1/audio/translations",
                        "standard_target_language": "en", "job_option": "translate_to", "model": settings.translation_model or None,
                        "method": "asr-then-text-translation", "formats": ["json", "text", "srt", "vtt"],
                        "timing": "source-speech-segments", "word_timing": False},
    }
