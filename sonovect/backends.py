"""Model execution adapters; no downstream application ownership."""
from contextlib import redirect_stdout
from pathlib import Path
import importlib.util
import logging
import os
import sys
import httpx
from .results import acoustic_result, native_result, speech_result
from .models import measurements_requested

logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    pass


def native_model_source(name, revision):
    """Resolve only catalogued native models and verify before loading."""
    from .assets import resolve, catalog
    aliases = {"paraformer-zh": "paraformer", "fsmn-vad": "fsmn", "ct-punc": "punc", "cam++": "cam"}
    alias = aliases.get(name)
    if name == "paraformer-zh" and revision == "v2.0.9":
        alias = "paraformer-v2.0.9"
    if alias is None or catalog()[alias]["revision"] != revision:
        raise RuntimeError("native_model_identity_not_in_catalog")
    return resolve(alias, os.getenv("MODELSCOPE_CACHE"),
                   offline=os.getenv("MODELSCOPE_OFFLINE", "1").lower() in {"1", "true", "yes"})


class SpeechBackend:
    def __init__(self, settings):
        self.settings = settings

    def available(self):
        return True

    def process(self, path: Path, key: str, options: dict):
        measure = measurements_requested(options)
        endpoint = "/transcribe/full" if options["analyze_sound"] or options.get("analyze_voice", False) or measure else "/transcribe"
        data = {"language": options["language"] or "auto", "speaker_identity": "false",
                "context": " ".join(options["hotwords"]),
                "analyze_sound": str(options["analyze_sound"]).lower(),
                "analyze_voice": str(options.get("analyze_voice", False)).lower()}
        if measure:
            data["measure_voice"] = "true"
        with path.open("rb") as audio, httpx.Client(timeout=self.settings.provider_timeout, trust_env=False) as client:
            response = client.post(self.settings.provider_url + endpoint,
                                   files={"files": ("audio.wav", audio, "application/octet-stream")}, data=data)
            response.raise_for_status()
            value = response.json()
        if "results" in value:
            if len(value["results"]) != 1:
                raise BackendError("invalid_provider_result_count")
            value = value["results"][0]
        if value.get("enrichment", {}).get("lanes", {}).get("speech", {}).get("state") != "completed":
            raise BackendError("speech_processing_failed")
        return speech_result(value, key, options["speakers"]), acoustic_result(value, key, options["analyze_sound"], options.get("analyze_voice", False), measure)


class FunASRBackend:
    def __init__(self, settings):
        self.settings = settings
        self.models = {}

    def available(self):
        return importlib.util.find_spec("funasr") is not None

    def process(self, path: Path, key: str, options: dict):
        # Model diagnostics go to stderr, including under a protocol host.
        with redirect_stdout(sys.stderr):
            from funasr import AutoModel
            speakers = options["speakers"]
            if speakers not in self.models:
                # Keep one pipeline resident when callers change speaker options.
                import gc
                self.models.clear()
                gc.collect()
                self.models[speakers] = AutoModel(
                    model=native_model_source(self.settings.model, self.settings.model_revision),
                    model_revision=self.settings.model_revision,
                    vad_model=native_model_source("fsmn-vad", "v2.0.4"), vad_model_revision="v2.0.4",
                    punc_model=native_model_source("ct-punc", "v2.0.4"), punc_model_revision="v2.0.4",
                    **({"spk_model": native_model_source("cam++", "v2.0.2"), "spk_model_revision": "v2.0.2"} if speakers else {}),
                    device=self.settings.device, disable_update=True, disable_pbar=True, trust_remote_code=False)
                if self.settings.measurements_enabled or (self.settings.voice_enabled and self.settings.voice_backend == "emotion2vec"):
                    from .vocal_context import capture_vad
                    capture_vad(self.models[speakers])
            kwargs = {"sentence_timestamp": True, "return_spk_res": speakers,
                      "return_spk_center": False, "batch_size": 1}
            if options["language"]:
                kwargs["language"] = options["language"]
            if options["hotwords"]:
                kwargs["hotword"] = " ".join(options["hotwords"])
            if self.settings.measurements_enabled or (self.settings.voice_enabled and self.settings.voice_backend == "emotion2vec"):
                self.models[speakers].sonovect_vad_regions = None
            values = self.models[speakers].generate(input=str(path), **kwargs)
        if not isinstance(values, list) or len(values) != 1:
            raise BackendError("invalid_funasr_result_count")
        result = native_result(values[0], key, speakers)
        measure = measurements_requested(options)
        if not options["analyze_sound"] and not options.get("analyze_voice", False) and not measure:
            return result, acoustic_result({}, key, False, False)
        stages = {}
        duration_ms = None
        for name, requested, url in [("events", options["analyze_sound"], self.settings.sound_url),
                                      ("measurements", measure, self.settings.measurements_url),
                                      ("vocal", options.get("analyze_voice", False), self.settings.voice_url)]:
            if not requested:continue
            try:
                data = {}
                if name == "measurements" or (name == "vocal" and self.settings.voice_backend == "emotion2vec"):
                    import json
                    import wave
                    from .vocal_context import speech_context
                    with wave.open(str(path), "rb") as audio:
                        duration_ms = round(audio.getnframes() * 1000 / audio.getframerate())
                    data = {"speech_context": json.dumps([speech_context(self.models[speakers].sonovect_vad_regions)])}
                with path.open("rb") as audio, httpx.Client(timeout=self.settings.provider_timeout, trust_env=False) as client:
                    response = client.post(url + "/analyze", files={"files": ("audio.wav", audio, "application/octet-stream")}, data=data)
                    response.raise_for_status();value = response.json()
                if "results" in value:
                    if len(value["results"]) != 1:raise BackendError("invalid_stage_result_count")
                    value = value["results"][0]
                stages[name] = {"payload": value}
            except Exception as exc:
                # Public results retain their stable failure code. Operators
                # can distinguish transport failures without logging media,
                # tokens, generated descriptions or arbitrary response bodies.
                response = getattr(exc, "response", None)
                logger.error("optional_stage_failed stage=%s type=%s upstream_status=%s",
                             name, type(exc).__name__, getattr(response, "status_code", None))
                stages[name] = {"error": name + "_analysis_failed"}
        return result, acoustic_result({"stage_payloads": stages, **({"duration_ms": duration_ms} if duration_ms is not None else {})}, key, options["analyze_sound"], options.get("analyze_voice", False), measure)


def build_backend(settings):
    return FunASRBackend(settings) if settings.backend == "funasr" else SpeechBackend(settings)
