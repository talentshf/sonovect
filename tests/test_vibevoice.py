import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
import httpx

from sonovect.api import create_app
from sonovect.backends import build_backend
from sonovect.config import Settings
from sonovect.media import MediaError
from sonovect.models import Options
from sonovect.setup import selection
from sonovect.vibevoice import normalize
from sonovect.worker import Worker
from sonovect.auth import provider_headers


ROWS = [{"Start time": 0.1, "End time": 0.4, "Speaker ID": 7, "Content": "你好。"},
        {"Start time": 0.5, "End time": 0.9, "Speaker ID": "7", "Content": "Hello!"}]


class VibeVoiceTests(unittest.TestCase):
    def settings(self, root, **kw):
        return Settings(data_dir=Path(root), token="vibevoice-test-token", backend="vibevoice", sound_enabled=False, **kw)

    def test_sentence_evidence_not_word_interpolation_or_personal_identity(self):
        result = normalize(json.dumps(ROWS), "a", 1)
        self.assertEqual([s["spk"] for s in result["sentence_info"]], [0, 1])
        self.assertEqual(result["sentence_info"][0]["start"], 100)
        self.assertNotIn("timestamp", result)
        self.assertNotIn("timestamp", result["sentence_info"][0])
        self.assertNotIn("spk", normalize(json.dumps(ROWS), "a", 1, False)["sentence_info"][0])
        self.assertEqual(normalize("[]", "a", 1)["text"], "")

    def test_invalid_evidence_rejected_instead_of_fabricated(self):
        for row in ({**ROWS[0], "Start time": True}, {**ROWS[0], "End time": 5},
                    {**ROWS[0], "Start time": -1}, {**ROWS[0], "Content": 1},
                    {**ROWS[0], "End time": float("nan")}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                normalize(json.dumps([row]), "a", 1)

    def test_route_is_explicit_and_defaults_do_not_change(self):
        selected = selection(route="vibevoice")
        self.assertEqual(selected["environment"]["SONOVECT_BACKEND"], "vibevoice")
        self.assertEqual(selected["download_bytes"], 0)
        self.assertTrue(selected["external_model_service_required"])
        self.assertEqual(selection()["route"], "qwen")
        with self.assertRaises(ValueError):
            selection(route="vibevoice", sound="ast")

    def test_readiness_uses_vllm_model_discovery_and_matches_served_name(self):
        import asyncio
        from sonovect.readiness import Readiness
        with TemporaryDirectory() as root:
            settings = self.settings(root)
            snapshot = {"available_workers": 1, "code": None}
            real = httpx.AsyncClient
            def upstream(request):
                self.assertEqual(request.url.path, "/v1/models")
                return httpx.Response(200, json={"data": [{"id": "vibevoice"}]})
            def factory(**kw): return real(transport=httpx.MockTransport(upstream), **kw)
            with patch("sonovect.readiness.Store.worker_snapshot", return_value=snapshot), patch("sonovect.readiness.httpx.AsyncClient", side_effect=factory):
                self.assertEqual(asyncio.run(Readiness(settings).get())["status"], "ready")
            self.assertEqual(settings.source_seconds_limit, 900)

    def test_durable_job_and_result_reads_do_not_repeat_inference(self):
        calls = []
        def upstream(request):
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "vibevoice"}]})
            self.assertEqual(request.url.path, "/v1/chat/completions")
            body = json.loads(request.content)
            calls.append(body)
            audio = body["messages"][1]["content"][0]["audio_url"]["url"]
            self.assertTrue(base64.b64decode(audio.split(",")[1]).startswith(b"RIFF"))
            self.assertIn("Sonovect", body["messages"][1]["content"][1]["text"])
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ROWS)}}]})
        real_client = httpx.Client
        def factory(**kw):
            return real_client(transport=httpx.MockTransport(upstream), **kw)
        with TemporaryDirectory() as root:
            path = Path(root) / "sample.wav"
            with wave.open(str(path), "wb") as w:
                w.setparams((1, 2, 16000, 0, "NONE", "not compressed")); w.writeframes(b"\0\0" * 16000)
            settings = self.settings(Path(root) / "jobs")
            with TestClient(create_app(settings)) as c:
                c.headers["Authorization"] = "Bearer " + settings.token
                response = c.post("/v1/jobs", files={"files": ("a.wav", path.read_bytes())},
                                  data={"options": Options(hotwords=["Sonovect"]).model_dump_json()})
                self.assertEqual(response.status_code, 202)
                job = response.json()["id"]
                with patch("sonovect.vibevoice.httpx.Client", side_effect=factory):
                    worker = Worker(settings)
                    self.assertFalse(build_backend(settings).identity().get("forced_aligner"))
                    self.assertTrue(worker.run_once())
                self.assertEqual(c.get("/v1/jobs/" + job).json()["status"], "succeeded")
                first = c.get(f"/v1/jobs/{job}/result").content
                self.assertEqual(first, c.get(f"/v1/jobs/{job}/result").content)
                self.assertEqual(c.get(f"/v1/jobs/{job}/result?format=srt").status_code, 200)
                self.assertEqual(len(calls), 1)

    def test_duration_guard_and_truncation_do_not_store_false_success(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "a.wav"
            with wave.open(str(path), "wb") as w:
                w.setparams((1, 2, 16000, 0, "NONE", "not compressed")); w.writeframes(b"\0\0" * 16000)
            backend = build_backend(self.settings(root, vibevoice_max_seconds=0.5))
            with self.assertRaisesRegex(MediaError, "duration_limit"):
                backend.process(path, "a", Options().wire())
            backend = build_backend(self.settings(root))
            real = httpx.Client
            def factory(**kw):
                return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                    "choices": [{"finish_reason": "length", "message": {"content": json.dumps(ROWS)}}]})), **kw)
            with patch("sonovect.vibevoice.httpx.Client", side_effect=factory), self.assertRaisesRegex(MediaError, "response_invalid"):
                backend.process(path, "a", Options().wire())

    def test_upstream_secret_uses_existing_file_without_url_or_error_echo(self):
        with TemporaryDirectory() as root:
            secret = Path(root) / "upstream-token"
            secret.write_text("synthetic-upstream-key\n"); secret.chmod(0o600)
            settings = self.settings(root, provider_token_file=secret)
            self.assertEqual(provider_headers(settings), {"Authorization": "Bearer synthetic-upstream-key"})
            secret.write_text("invalid\nheader")
            with self.assertRaisesRegex(RuntimeError, "^provider_token_unavailable$"):
                provider_headers(settings)

    def test_compatible_result_omits_word_timing_and_recovers_same_task(self):
        with TemporaryDirectory() as root:
            key = Path(root) / "signing-key"
            key.write_bytes(b"synthetic-persistent-signing-key-32"); key.chmod(0o600)
            settings = self.settings(root, compat_model="sonovect-vibevoice", compat_public_url="https://asr.example.test",
                                     compat_signing_key_file=key, compat_input_hosts=("media.example.test",))
            def download(settings, source):
                with wave.open(source["path"], "wb") as w:
                    w.setparams((1, 2, 16000, 0, "NONE", "not compressed")); w.writeframes(b"\0\0" * 16000)
                import hashlib
                raw = Path(source["path"]).read_bytes()
                return {**source, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            count = []
            def upstream(request):
                if request.url.path == "/v1/models":
                    return httpx.Response(200, json={"data": [{"id": "vibevoice"}]})
                count.append(request.url.path)
                return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ROWS)}}]})
            real = httpx.Client
            def factory(**kw): return real(transport=httpx.MockTransport(upstream), **kw)
            c = TestClient(create_app(settings)); c.headers["Authorization"] = "Bearer " + settings.token
            try:
                with patch("sonovect.vibevoice.httpx.Client", side_effect=factory):
                    meta = c.get("/api/v1/models").json()["data"][0]["capabilities"]
                    self.assertFalse(meta["word_timestamps"])
                    self.assertTrue(meta["speaker_diarization"])
                    response = c.post("/api/v1/services/audio/asr/transcription", headers={"X-DashScope-Async": "enable"}, json={
                        "model": "sonovect-vibevoice", "input": {"file_urls": ["https://media.example.test/audio"]},
                        "parameters": {"diarization_enabled": True}})
                    self.assertEqual(response.status_code, 202)
                    job = response.json()["output"]["task_id"]
                    self.assertTrue(Worker(settings, downloader=download).run_once())
                output = c.get("/api/v1/tasks/" + job).json()["output"]
                self.assertEqual(output["task_status"], "SUCCEEDED")
                link = output["results"][0]["transcription_url"]
                content = c.get(link).content
                row = json.loads(content)["transcripts"][0]["sentences"][0]
                self.assertNotIn("words", row)
                self.assertEqual(row["speaker_id"], 0)
                c.close(); c = TestClient(create_app(settings))
                self.assertEqual(c.get(link).content, content)
                self.assertEqual(len(count), 1)
            finally:
                c.close()
