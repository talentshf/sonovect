from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soxr
from fastapi.testclient import TestClient

from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.realtime import Start, capability, create_realtime_app
from sonovect.setup import selection
from sonovect.vibevoice_stream import LiveText, VibeVoiceStreamingEngine, speaker_segments


class Synthetic(VibeVoiceStreamingEngine):
    def __init__(self, settings):
        super().__init__(settings)
        self.model = Mock()
        self.model.init_streaming_state.return_value = {}
        self.processor = SimpleNamespace(tokenizer=object())
        self.windows = []

    def _step(self, state, window):
        self.windows.append(window.copy())
        state["texts"].append("\nSpeaker 4:你好" if len(self.windows) == 1 else "\nSpeaker 8:Hello")


class VibeVoiceStreamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name) / "jobs", token="stream-test-token",
                                 realtime_enabled=True, realtime_backend="vibevoice-1.5b", realtime_model_path=self.temp.name)
        self.engine = Synthetic(self.settings)
        self.torch = patch.dict("sys.modules", {"torch": SimpleNamespace(inference_mode=nullcontext)})
        self.torch.start()

    def tearDown(self):
        self.torch.stop(); self.temp.cleanup()

    def test_pinned_checkpoint_and_setup_are_specific_to_small_streaming_model(self):
        value = selection(route="vibevoice-1.5b")
        self.assertEqual(value["container_count"], 1)
        self.assertEqual(value["download_bytes"], 5644393692)
        self.assertEqual(value["models"]["vibevoice-stream-1.5b"]["revision"], "4262d23d8a539a6530cf64fbd0b1751ef9a30853")
        self.assertTrue(capability(self.settings)["speakers"])
        with self.assertRaises(ValueError): replace(self.settings, realtime_max_seconds=481)
        with self.assertRaises(ValueError): selection(route="vibevoice-1.5b", sound="ast")

    def test_stateful_resampling_lookahead_and_tail_are_frame_boundary_independent(self):
        audio = (np.sin(np.arange(16000 * 5) * 0.1) * 20000).astype("<i2")
        a = self.engine.start(Start(type="start", hotwords=["Sonovect"]))
        # The first two seconds must buffer, not prematurely encode a window.
        self.engine.push(a, audio[:32000].tobytes())
        self.assertEqual(len(self.engine.windows), 0)
        self.engine.push(a, audio[32000:64000].tobytes())
        self.assertEqual(len(self.engine.windows), 1)
        self.assertEqual(len(self.engine.windows[0]), 83200)
        self.engine.push(a, audio[64000:].tobytes())
        result = self.engine.finish(a)
        self.assertEqual(a["received_samples"], 120000)
        self.assertEqual(a["advanced_samples"], 140800)
        self.assertEqual(len(self.engine.windows), 2)
        self.assertEqual([s["speaker_id"] for s in result.speaker_segments], [0, 1])
        self.assertEqual(self.engine.model.init_streaming_state.call_args.kwargs["context_info"], "Sonovect")
        first_windows = list(self.engine.windows)
        other = Synthetic(self.settings); b = other.start(Start(type="start"))
        # Odd counts of samples and arbitrary tiny frames cannot lose half
        # samples at the 16k -> 24k boundary or change the encoded windows.
        for frame in np.array_split(audio, 137): other.push(b, frame.tobytes())
        other.finish(b)
        self.assertEqual(len(other.windows), 2)
        for one, two in zip(first_windows, other.windows): np.testing.assert_allclose(one, two, atol=1e-6)
        with self.assertRaisesRegex(RuntimeError, "already_finished"): other.finish(b)

    def test_exact_chunk_advance_is_not_decoded_twice_during_flush(self):
        state = self.engine.start(Start(type="start"))
        # Three chunks at 24 kHz equal 140800 input samples at 16 kHz.
        self.engine.push(state, np.zeros(140800, dtype="<i2").tobytes())
        self.engine.finish(state)
        self.assertEqual(len(self.engine.windows), 3)
        self.assertEqual(state["received_samples"], 211200)

    def test_label_parser_preserves_raw_text_without_inventing_timing(self):
        text = "\nSpeaker 7:甲\nSpeaker 2:乙\nSpeaker 7:丙"
        rows = speaker_segments(text)
        self.assertEqual([r["speaker_id"] for r in rows], [0, 1, 0])
        self.assertFalse(any("start" in row or "timestamp" in row for row in rows))
        self.assertEqual(speaker_segments("no speaker evidence"), [])

    def test_shared_live_protocol_transports_speaker_evidence_and_full_snapshots(self):
        app = create_app(self.settings); app.state.realtime_engine = self.engine
        with TestClient(app) as client, client.websocket_connect("/v1/realtime", headers={"Authorization": "Bearer stream-test-token"}) as ws:
            ws.send_json({"type": "start"})
            self.assertTrue(ws.receive_json()["capabilities"]["speakers"])
            for _ in range(2):
                ws.send_bytes(b"\0\0" * 32000); part = ws.receive_json()
            self.assertEqual(part["speaker_segments"][0]["speaker_id"], 0)
            self.assertIn("Speaker 4:", part["text"])
            ws.send_json({"type": "finish"}); final = ws.receive_json()
            self.assertEqual(final["type"], "final")
            self.assertNotIn("timestamp", final)

    def test_standalone_discovery_is_authenticated_without_starting_a_file_queue(self):
        app = create_realtime_app(self.settings)
        with TestClient(app) as client:
            self.assertEqual(client.get("/v1/capabilities").status_code, 401)
            value = client.get("/v1/capabilities", headers={"Authorization": "Bearer stream-test-token"}).json()
            self.assertEqual(value["realtime"]["model_family"], "vibevoice-streaming-1.5b")
            self.assertTrue(value["realtime"]["speakers"])
            self.assertEqual(client.get("/v1/jobs", headers={"Authorization": "Bearer stream-test-token"}).status_code, 404)
