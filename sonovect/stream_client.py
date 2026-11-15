"""OpenAI transcription-session client; PCM24k, manual turn commit, no retries."""
import base64
import json
from urllib.parse import urlsplit, urlunsplit


def events(client, pcm, *, language=None, hotwords=None):
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise RuntimeError("install_stream_client_extra") from None
    parts = urlsplit(client.url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("invalid_stream_url")
    url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                     parts.path.rstrip("/") + "/v1/realtime", "intent=transcription", ""))
    try:
        with connect(url, additional_headers={"Authorization": client.http.headers["Authorization"]},
                     open_timeout=10, close_timeout=5, max_size=1024**2, proxy=None) as ws:
            def receive():
                value = json.loads(ws.recv(timeout=300))
                if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                    raise ValueError("invalid_stream_response")
                if value["type"] == "error":
                    raise RuntimeError("realtime_request_failed")
                return value
            created = receive()
            if created["type"] != "session.created":
                raise ValueError("invalid_stream_response")
            yield created
            transcription = {}
            if language: transcription["language"] = language
            if hotwords: transcription["keywords"] = hotwords
            ws.send(json.dumps({"type": "session.update", "session": {"type": "transcription", "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 24000}, "transcription": transcription, "turn_detection": None}}}}))
            updated = receive()
            if updated["type"] != "session.updated":
                raise ValueError("invalid_stream_response")
            yield updated
            # Each 10-second committed item may produce append-only ASR deltas.
            # This is client-side chunking, not a claim of server speech endpoint detection.
            sent = False
            while chunk := pcm.read(480000):
                if len(chunk) % 2:
                    raise ValueError("incomplete_pcm_sample")
                for start in range(0, len(chunk), 48000):
                    ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(chunk[start:start+48000]).decode()}))
                ws.send('{"type":"input_audio_buffer.commit"}')
                sent = True
                while True:
                    value = receive()
                    yield value
                    if value["type"] == "conversation.item.input_audio_transcription.failed":
                        raise RuntimeError("realtime_transcription_failed")
                    if value["type"] == "conversation.item.input_audio_transcription.completed":
                        break
            if not sent:
                raise ValueError("empty_pcm")
    except (ValueError, RuntimeError):
        raise
    except Exception:
        raise RuntimeError("realtime_connection_failed") from None


def run(client, path=None, stdin=None, *, language=None, hotwords=None):
    import wave
    if stdin is not None:
        yield from events(client, stdin, language=language, hotwords=hotwords)
    else:
        with wave.open(path, "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 24000, "NONE"):
                raise ValueError("stream_requires_24khz_mono_pcm16_wav")
            class Frames:
                def read(self, size): return audio.readframes(size // 2)
            yield from events(client, Frames(), language=language, hotwords=hotwords)
