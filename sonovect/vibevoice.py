"""VibeVoice's official vLLM wire protocol, adapted to durable file jobs.

The endpoint is operator-owned. No retries, model downloads, implicit chunking,
word interpolation, or cross-recording speaker identities are introduced here.
"""
import base64
import json
import math
import wave

import httpx

from .media import MediaError
from .models import transcript_json
from .recognition import Recognition, speech_evidence
from .results import acoustic_result
from .auth import provider_headers


class VibeVoiceBackend:
    def __init__(self, settings):
        self.settings = settings

    def available(self):
        return True

    def identity(self):
        # This freezes the operator-selected revision, not an attestation of
        # arbitrary remote weights. Deployment must verify the upstream too.
        with httpx.Client(timeout=5, trust_env=False, headers=provider_headers(self.settings)) as client:
            response = client.get(self.settings.provider_url + "/v1/models")
            response.raise_for_status()
            models = response.json().get("data", [])
        if not any(isinstance(m, dict) and m.get("id") == self.settings.vibevoice_model for m in models):
            raise RuntimeError("vibevoice_model_unavailable")
        model = {"model": "microsoft/VibeVoice-ASR", "revision": self.settings.vibevoice_revision}
        return {"backend": "vibevoice", "asr": model, "speaker_diarization": model}

    def process(self, path, key, options):
        if options.get("analyze_sound") or options.get("analyze_voice") or options.get("measure_voice"):
            raise MediaError("vibevoice_optional_analysis_not_supported")
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        if duration > self.settings.vibevoice_max_seconds:
            raise MediaError("vibevoice_duration_limit_exceeded")
        prompt = f"This is a {duration:.2f} seconds audio"
        if options.get("hotwords"):
            prompt += ", with extra info: " + ", ".join(options["hotwords"])
        if options.get("language"):
            prompt += ". Language hint: " + options["language"]
        prompt += "\nPlease transcribe it with these keys: Start time, End time, Speaker ID, Content"
        payload = {"model": self.settings.vibevoice_model, "temperature": 0.0,
                   "max_tokens": self.settings.vibevoice_max_tokens, "stream": False,
                   "messages": [
                       {"role": "system", "content": "You are a helpful assistant that transcribes audio input into text output in JSON format."},
                       {"role": "user", "content": [
                           {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")}},
                           {"type": "text", "text": prompt}]}]}
        try:
            # A response bound and explicit finish reason prevent truncated or
            # runaway generations from becoming successful stored transcripts.
            with httpx.Client(timeout=self.settings.provider_timeout, trust_env=False, headers=provider_headers(self.settings)) as client:
                with client.stream("POST", self.settings.provider_url + "/v1/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for part in response.iter_bytes():
                        body.extend(part)
                        if len(body) > 4 * 1024**2:
                            raise ValueError("response_too_large")
            choice = json.loads(body)["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("incomplete_generation")
            result = normalize(choice["message"]["content"], key, duration, options["speakers"])
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            raise MediaError("vibevoice_response_invalid_or_unavailable") from None
        return Recognition(result, acoustic_result({}, key, False, False), speech_evidence({}, result))


def normalize(content, key, duration, speakers=True):
    if not isinstance(content, str):
        raise ValueError("invalid_content")
    content = content.strip()
    if content.startswith("```json\n") and content.endswith("```"):
        content = content[8:-3].strip()
    rows = json.loads(content)
    if not isinstance(rows, list):
        raise ValueError("invalid_segments")
    sentences, identities = [], {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("Content"), str):
            raise ValueError("invalid_segment")
        text = row["Content"]
        start, end = row.get("Start time"), row.get("End time")
        if any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)):
            raise ValueError("invalid_timing")
        if not 0 <= start <= end <= duration + 0.1:
            raise ValueError("invalid_timing")
        sentence = {"text": text, "start": round(start * 1000), "end": round(end * 1000)}
        speaker = row.get("Speaker ID")
        if speakers and speaker is not None:
            if type(speaker) not in (str, int) or (isinstance(speaker, str) and not speaker.strip()):
                raise ValueError("invalid_speaker")
            identity = (type(speaker).__name__, speaker)
            sentence["spk"] = identities.setdefault(identity, len(identities))
        sentences.append(sentence)
    # Sentence boundaries are not word alignments: do not fill timestamp/words.
    return transcript_json({"key": key, "text": "".join(s["text"] for s in sentences), "sentence_info": sentences})
