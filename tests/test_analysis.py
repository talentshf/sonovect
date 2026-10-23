import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import httpx

from fastapi.testclient import TestClient
from pydantic import ValidationError

from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.models import Analysis, VoiceMeasurement, Options
from sonovect.client import Client
from sonovect.results import acoustic_result, native_result
from sonovect.setup import selection
from sonovect.vocal_context import capture_vad


class AnalysisTests(unittest.TestCase):
    def test_explicit_default_options_have_one_idempotency_identity(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Settings(data_dir=Path(tmp), token="options-test"))) as c:
            c.headers["Authorization"]="Bearer options-test"
            payload={"files":{"files":("a.wav",b"audio")},"headers":{"Idempotency-Key":"same-request"}}
            first=c.post("/v1/jobs",**payload)
            again=c.post("/v1/jobs",data={"options":'{"measure_voice":false}'},**payload)
            self.assertEqual((first.status_code,again.status_code),(202,200))
            self.assertEqual(first.json()["id"],again.json()["id"])
            self.assertFalse(first.json()["options"]["measure_voice"])

    def test_client_sends_explicit_independent_measurement_option(self):
        bodies=[]
        def handle(request):
            bodies.append(request.read());return httpx.Response(202,json={"id":"test"})
        with TemporaryDirectory() as tmp:
            audio=Path(tmp)/"a.wav";audio.write_bytes(b"audio")
            client=Client(token="test",transport=httpx.MockTransport(handle))
            try:
                client.submit([audio]);client.submit([audio],Options(measure_voice=True))
            finally:client.close()
        self.assertIn(b'"measure_voice":false',bodies[0])
        self.assertIn(b'"measure_voice":true',bodies[1])

    def payload(self):
        return {"duration_ms": 1000, "stage_payloads": {
            "events": {"payload": {"parse_valid": True, "events_valid": True,
                "engine": {"model": "ast", "revision": "fixed"}, "events": [{"label": "Rain"}]}},
            "vocal": {"payload": {"parse_valid": True, "vocal_valid": True,
                "engine": {"model": "emotion2vec", "revision": "fixed"},
                "emotions": [{"label": "NEUTRAL"}]}},
            "measurements": {"payload": {"parse_valid": True, "measurements_valid": True,
                "engine": {"model": "sonovect/pyin-pcm-rms", "revision": "1"}, "measurements": [dict(
                    kind="pitch", value=120.0, unit="Hz", method="pyin-50-600hz", status="measured",
                    start_ms=0, end_ms=1000, temporal_resolution="analysis-window")]}}}}

    def test_one_analysis_schema_and_explicit_measurements_preserve_speech(self):
        value=self.payload();before=copy.deepcopy(value)
        acoustic=acoustic_result(value,"a",True,True)
        Analysis.model_validate(acoustic)
        self.assertEqual(acoustic["measurements"],[])
        self.assertEqual(acoustic["schema_version"],"audio-analysis-v1")
        numeric=acoustic_result(value,"a",True,True,True)
        Analysis.model_validate(numeric)
        self.assertEqual(numeric["measurements"][0]["value"],120)
        self.assertEqual(value,before)
        speech={"text":"原生文本。","timestamp":[[0,500]]}
        self.assertEqual(native_result(speech,"a",False),{**speech,"key":"a"})

    def test_corrupt_measurement_fails_only_measurements_stage(self):
        for patch in [{"value": float("nan")}, {"unit": "dBFS"}, {"end_ms": 1001},
                      {"value": True}, {"value": 1000.0}, {"start_ms": 1000}]:
            value = self.payload();value["stage_payloads"]["measurements"]["payload"]["measurements"][0].update(patch)
            result = acoustic_result(value, "a", True, True, True)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["events"], [{"label": "Rain", "temporal_resolution": "unspecified"}])
            self.assertEqual(result["measurements"], [])
            self.assertEqual(result["emotions"][0]["label"], "NEUTRAL")
            self.assertEqual(result["stages"]["vocal"]["status"], "completed")

    def test_unrequested_payload_cannot_leak_measurements_or_warnings(self):
        value = self.payload();value["stage_payloads"]["vocal"]["payload"]["warnings"] = ["no_usable_speech"]
        result = acoustic_result(value, "a", True, False, False)
        self.assertEqual(result["measurements"], [])
        self.assertEqual(result["quality"]["warnings"], [])

    def test_unavailable_value_has_explicit_status_and_no_infinity(self):
        value = dict(kind="relative-energy", unit="dBFS", method="pcm-rms", status="unavailable", start_ms=0, end_ms=1000)
        self.assertIsNone(VoiceMeasurement(**value).value)
        for extra in [{"value": float("inf")}, {"value": 0.0}, {"status": "measured"}, {"status": "measured", "value": 1.0}]:
            with self.assertRaises(ValidationError):VoiceMeasurement(**(value | extra))

    def test_deployment_choices_do_not_install_moss_or_duplicate_vad(self):
        for route in ["cpu", "qwen"]:
            plain = selection(route=route, sound="ast")
            extended = selection(route=route, sound="ast", voice="emotion2vec")
            self.assertEqual(set(extended["models"]) - set(plain["models"]), {"emotion2vec-base"})
            self.assertEqual(extended["environment"]["COMPOSE_PROFILES"], "analysis")
            self.assertNotIn("MOSS_AUDIO_MODEL", extended["environment"])
            self.assertTrue(extended["experimental"])

    def test_unsupported_numeric_backend_rejected_before_admission(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Settings(data_dir=Path(tmp), token="vocal-test", voice_enabled=True, voice_url="http://vocal"))) as c:
            c.headers["Authorization"] = "Bearer vocal-test"
            r = c.post("/v1/jobs", files={"files": ("a.wav", b"audio")}, data={"options": json.dumps({"measure_voice": True})})
            self.assertEqual(r.status_code, 422)
            with c.app.state.store.connect() as con:self.assertEqual(con.execute("select count(*) from jobs").fetchone()[0], 0)

    def test_vad_capture_observes_one_existing_call_without_mutating_it(self):
        class Pipeline:
            vad_model = object()
            calls = 0
            def inference(self, *, model):
                self.calls += 1
                return [{"value": [[1, 20]]}] if model is self.vad_model else [{"text": "speech"}]
        model = capture_vad(Pipeline())
        result = model.inference(model=model.vad_model)
        self.assertEqual(model.calls, 1)
        self.assertEqual(model.sonovect_vad_regions, [[1, 20]])
        result[0]["value"].clear()
        model.inference(model=object())
        self.assertEqual(model.sonovect_vad_regions, [[1, 20]])


if __name__ == "__main__":
    unittest.main()
