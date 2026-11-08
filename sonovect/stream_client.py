"""Live client: emit replaceable snapshots; never reconnect or submit a job."""
import json
from urllib.parse import urlsplit, urlunsplit

from .realtime import Start


def events(client, pcm, *, language=None, hotwords=None):
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise RuntimeError("install_stream_client_extra") from None
    options = Start(type="start", language=language, hotwords=hotwords or [])
    parts = urlsplit(client.url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("invalid_stream_url")
    url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc,
                      parts.path.rstrip("/") + "/v1/realtime", "", ""))
    try:
        with connect(url, additional_headers={"Authorization": client.http.headers["Authorization"]},
                     open_timeout=10, close_timeout=5, max_size=1024**2, proxy=None) as ws:
            ws.send(options.model_dump_json())
            session_id, sequence = None, 0

            def receive(expected):
                nonlocal session_id, sequence
                value = json.loads(ws.recv(timeout=300))
                if not isinstance(value, dict):
                    raise ValueError("invalid_stream_response")
                if value.get("type") == "error":
                    allowed = {"realtime_busy", "realtime_timeout", "realtime_invalid_request",
                               "invalid_pcm_frame", "realtime_duration_limit_exceeded",
                               "realtime_engine_unavailable", "realtime_engine_failed"}
                    raise RuntimeError(value.get("code") if value.get("code") in allowed else "realtime_failed")
                if (value.get("type") != expected or type(value.get("sequence")) is not int
                        or value["sequence"] != sequence + 1 or not isinstance(value.get("session_id"), str)
                        or (session_id is not None and value["session_id"] != session_id)):
                    raise ValueError("invalid_stream_response")
                if expected in {"partial", "final"} and not isinstance(value.get("text"), str):
                    raise ValueError("invalid_stream_response")
                session_id, sequence = value["session_id"], value["sequence"]
                return value

            yield receive("started")
            sent = False
            while chunk := pcm.read(64000):
                if len(chunk) % 2:
                    raise ValueError("incomplete_pcm_sample")
                ws.send(chunk)
                sent = True
                yield receive("partial")
            if not sent:
                raise ValueError("empty_pcm")
            ws.send('{"type":"finish"}')
            yield receive("final")
    except (ValueError, RuntimeError):
        raise
    except Exception:
        # WebSocket/library exceptions can contain URLs/headers. Never echo them.
        raise RuntimeError("realtime_connection_failed") from None


def run(client, path=None, stdin=None, *, language=None, hotwords=None):
    import wave
    if stdin is not None:
        yield from events(client, stdin, language=language, hotwords=hotwords)
    else:
        with wave.open(path, "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("stream_requires_16khz_mono_pcm16_wav")
            class Frames:
                def read(self, size):
                    return audio.readframes(size // 2)
            yield from events(client, Frames(), language=language, hotwords=hotwords)
