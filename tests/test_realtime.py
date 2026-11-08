import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dataclasses import replace

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sonovect.api import create_app
from sonovect.client import Client
from sonovect.config import Settings
from sonovect.realtime import QwenStreamingEngine, Start
from sonovect.stream_client import events


class Engine:
    def __init__(self):
        self.starts, self.finishes, self.pushed = 0, 0, []
    def start(self, options):
        self.starts += 1
        return SimpleNamespace(text="")
    def push(self, state, pcm):
        self.pushed.append(pcm)
        state.text = "可修改草稿" if len(self.pushed) == 1 else "修正后的文字"
        return state.text
    def finish(self, state):
        self.finishes += 1
        return state.text + "。"


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name) / "jobs", token="realtime-test-token",
                                 realtime_enabled=True, realtime_model_path=self.tmp.name)
        self.app = create_app(self.settings)
        self.engine = self.app.state.realtime_engine = Engine()
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer " + self.settings.token}

    def tearDown(self):
        self.client.close(); self.tmp.cleanup()

    def test_live_frames_precede_finish_and_snapshots_replace_previous_text(self):
        with self.client.websocket_connect("/v1/realtime", headers=self.headers) as ws:
            ws.send_json({"type": "start", "hotwords": ["Sonovect"]})
            start = ws.receive_json()
            self.assertEqual(start["type"], "started")
            ws.send_bytes(b"\0\0" * 8000)
            one = ws.receive_json()
            self.assertEqual(one["type"], "partial")
            self.assertEqual(self.engine.finishes, 0)
            ws.send_bytes(b"\0\0" * 8000)
            two = ws.receive_json()
            self.assertEqual(two["text"], "修正后的文字")
            ws.send_json({"type": "finish"})
            final = ws.receive_json()
            self.assertEqual(final["text"], "修正后的文字。")
            self.assertEqual(final["type"], "final")
            self.assertEqual(final["received_audio_ms"], 1000)
            self.assertEqual(final["sequence"], 4)
            self.assertNotIn("speaker", final)
            self.assertNotIn("timestamp", final)

    def test_authentication_before_audio_and_query_token_never_accepted(self):
        for url, headers in [("/v1/realtime", {}), ("/v1/realtime?token=" + self.settings.token, {})]:
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(url, headers=headers):
                    pass
        self.assertEqual(self.engine.starts, 0)

    def test_disabled_route_rejects_without_model_loading(self):
        app = create_app(Settings(data_dir=Path(self.tmp.name) / "disabled", token=self.settings.token))
        with TestClient(app) as c, self.assertRaises(WebSocketDisconnect):
            with c.websocket_connect("/v1/realtime", headers=self.headers):
                pass

    def test_busy_and_disconnect_release_session_without_finishing_or_retrying(self):
        with self.client.websocket_connect("/v1/realtime", headers=self.headers) as first:
            first.send_json({"type": "start"}); first.receive_json()
            with self.client.websocket_connect("/v1/realtime", headers=self.headers) as second:
                self.assertEqual(second.receive_json()["code"], "realtime_busy")
        with self.client.websocket_connect("/v1/realtime", headers=self.headers) as third:
            third.send_json({"type": "start"}); third.receive_json()
        self.assertEqual(self.engine.starts, 2)
        self.assertEqual(self.engine.finishes, 0)

    def test_invalid_frames_and_start_never_reach_model(self):
        with self.client.websocket_connect("/v1/realtime", headers=self.headers) as ws:
            ws.send_json({"type": "start", "sample_rate": 48000})
            self.assertEqual(ws.receive_json()["code"], "realtime_invalid_request")
        self.assertEqual(self.engine.starts, 0)
        for pcm in (b"1", b"", b"\0\0" * 32001):
            with self.client.websocket_connect("/v1/realtime", headers=self.headers) as ws:
                ws.send_json({"type": "start"}); ws.receive_json(); ws.send_bytes(pcm)
                self.assertEqual(ws.receive_json()["code"], "invalid_pcm_frame")
        self.assertEqual(self.engine.pushed, [])

    def test_sdk_adapter_uses_native_streaming_state_and_flushes_tail(self):
        import numpy as np
        engine = QwenStreamingEngine(self.settings)
        from unittest.mock import Mock
        engine.model = Mock()
        state = SimpleNamespace(text="tail")
        engine.model.init_streaming_state.return_value = state
        self.assertIs(engine.start(Start(type="start")), state)
        self.assertEqual(engine.push(state, b"\0\x80\xff\x7f"), "tail")
        audio, actual = engine.model.streaming_transcribe.call_args.args
        self.assertIs(actual, state)
        self.assertTrue(np.allclose(audio, [-1, 32767 / 32768]))
        self.assertEqual(engine.finish(state), "tail")
        engine.model.finish_streaming_transcribe.assert_called_once_with(state)

    def test_duration_and_idle_limits_fail_explicitly(self):
        settings = replace(self.settings, realtime_max_seconds=0.01, realtime_idle_seconds=0.03)
        app = create_app(settings); app.state.realtime_engine = Engine()
        with TestClient(app) as c:
            with c.websocket_connect("/v1/realtime", headers=self.headers) as ws:
                ws.send_json({"type": "start"}); ws.receive_json()
                ws.send_bytes(b"\0\0" * 161)
                self.assertEqual(ws.receive_json()["code"], "realtime_duration_limit_exceeded")
            with c.websocket_connect("/v1/realtime", headers=self.headers) as ws:
                ws.send_json({"type": "start"}); ws.receive_json()
                self.assertEqual(ws.receive_json()["code"], "realtime_timeout")

    def test_model_slot_stays_busy_until_timed_out_inference_actually_ends(self):
        import threading
        import time
        release = threading.Event()
        class Slow(Engine):
            def push(self, state, pcm):
                release.wait(2)
                return "unfinished"
        settings = replace(self.settings, realtime_max_seconds=0.03, realtime_idle_seconds=0.03)
        app = create_app(settings); app.state.realtime_engine = Slow()
        with TestClient(app) as c:
            try:
                with c.websocket_connect("/v1/realtime", headers=self.headers) as ws:
                    ws.send_json({"type": "start"}); ws.receive_json()
                    ws.send_bytes(b"\0\0")
                    self.assertEqual(ws.receive_json()["code"], "realtime_timeout")
                with c.websocket_connect("/v1/realtime", headers=self.headers) as ws:
                    self.assertEqual(ws.receive_json()["code"], "realtime_busy")
            finally:
                release.set()

    def test_real_websocket_client_roundtrip_over_loopback(self):
        import socket
        import threading
        import time
        import uvicorn
        sock = socket.socket(); sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", ws_max_size=64000))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 3
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.started)
            import wave
            from contextlib import redirect_stdout
            from sonovect.cli import main
            path = Path(self.tmp.name) / "live.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed")); wav.writeframes(b"\0\0" * 40000)
            out = io.StringIO()
            with patch.dict("os.environ", {"SONOVECT_URL": f"http://127.0.0.1:{port}",
                                          "SONOVECT_TOKEN": self.settings.token, "SONOVECT_TOKEN_FILE": ""}), redirect_stdout(out):
                self.assertEqual(main(["stream", str(path), "--language", "Chinese"]), 0)
            result = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual([v["type"] for v in result], ["started", "partial", "partial", "final"])
            self.assertEqual(result[-1]["received_audio_ms"], 2500)
            self.assertEqual(self.engine.finishes, 1)
        finally:
            server.should_exit = True; thread.join(3); sock.close()
        self.assertFalse(thread.is_alive())

    def test_client_uses_header_auth_validates_sequence_and_never_reconnects(self):
        class Socket:
            def __init__(self): self.sent = []; self.index = 0
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def send(self, value): self.sent.append(value)
            def recv(self, **kw):
                self.index += 1
                return json.dumps({"session_id": "s", "sequence": self.index,
                    "type": ["started", "partial", "final"][self.index - 1], "text": "稿"})
        sock = Socket()
        c = Client(url="https://example.test", token=self.settings.token)
        try:
            with patch("websockets.sync.client.connect", return_value=sock) as connect:
                result = list(events(c, io.BytesIO(b"\0\0" * 100)))
                self.assertEqual([v["type"] for v in result], ["started", "partial", "final"])
                connect.assert_called_once()
                self.assertEqual(connect.call_args.kwargs["additional_headers"], self.headers)
                self.assertNotIn(self.settings.token, connect.call_args.args[0])
                self.assertEqual(sock.sent[-1], '{"type":"finish"}')
        finally:
            c.close()
