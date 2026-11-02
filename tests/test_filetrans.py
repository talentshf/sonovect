"""Consumer-shaped protocol and persistence tests, no inference or network."""
from dataclasses import replace
import hashlib
import http.client
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
import wave

from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.models import Options
from sonovect.recognition import Recognition, speech_evidence
from sonovect.remote_input import input_url, download_source
from sonovect.media import MediaError
from sonovect.store import Store
from sonovect.worker import Worker


IDENTITY = {"backend": "synthetic", "asr": {"model": "fixture", "revision": "fixed"},
            "forced_aligner": {"model": "aligner", "revision": "fixed"},
            "speaker_diarization": {"model": "speaker", "revision": "fixed"}}


class Engine:
    def __init__(self): self.calls = 0; self.text = "真实词证据。"
    def identity(self): return IDENTITY
    def process(self, path, key, options):
        self.calls += 1
        transcript = {"key": key, "text": self.text, "sentence_info": [
            {"text": self.text, "start": 100, "end": 500, **({"spk": 0} if options["speakers"] else {})}]}
        evidence = speech_evidence({"segments": [{"text": self.text, "start_ms": 100, "end_ms": 500,
            "words": [{"text": "真实词证据", "start_ms": 100, "end_ms": 450}]}]}, transcript)
        return Recognition(transcript, {"key": key, "status": "not_requested"}, evidence)


class FiletransTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        key = root / "signing.key"; key.write_bytes(b"synthetic-persistent-signing-key-32"); key.chmod(0o600)
        self.settings = Settings(data_dir=root / "jobs", token="synthetic-bearer", sound_enabled=False,
            compat_model="fixture-asr", compat_public_url="https://asr.example.test", compat_signing_key_file=key,
            compat_input_hosts=("media.example.test",))
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
        self.audio = b.getvalue(); self.digest = hashlib.sha256(self.audio).hexdigest()
        self.engine = Engine(); self.worker = Worker(self.settings, self.engine, self.download)
        self.client = self.open()
    def open(self):
        app = create_app(self.settings); app.state.engine_identity = lambda: IDENTITY
        return TestClient(app)
    def tearDown(self): self.client.close(); self.temp.cleanup()
    def download(self, settings, source):
        if source.get("sha256") and source["sha256"] != self.digest:
            raise MediaError("input_integrity_failed")
        Path(source["path"]).write_bytes(self.audio)
        return {**source, "sha256": self.digest, "size": len(self.audio)}
    def submit(self, *, key=None, digest=None, parameters=None, url=None):
        headers = {"Authorization": "Bearer " + self.settings.token, "X-DashScope-Async": "enable"}
        if key: headers["Idempotency-Key"] = key
        if digest: headers["X-Input-SHA256"] = digest
        return self.client.post("/api/v1/services/audio/asr/transcription", headers=headers, json={
            "model": "fixture-asr", "input": {"file_urls": [url or "https://media.example.test/audio?signature=private"]},
            "parameters": parameters or {}})
    def status(self, job):
        return self.client.get("/api/v1/tasks/" + job, headers={"Authorization": "Bearer " + self.settings.token})

    def test_submit_poll_download_reopen_and_native_view(self):
        response = self.submit(parameters={"diarization_enabled": True, "vocabulary": {"术语": 4}})
        self.assertEqual(response.status_code, 202)
        job = response.json()["output"]["task_id"]
        self.assertEqual(self.status(job).json()["output"]["task_status"], "PENDING")
        self.worker.run_once()
        output = self.status(job).json()["output"]
        self.assertEqual(output["task_status"], "SUCCEEDED")
        link = output["results"][0]["transcription_url"]
        result = self.client.get(link)
        row = result.json()["transcripts"][0]["sentences"][0]
        self.assertEqual((row["begin_time"], row["end_time"], row["speaker_id"]), (100, 500, 0))
        self.assertEqual(row["words"][0]["text"], "真实词证据")
        self.client.close(); self.client = self.open()
        self.assertEqual(self.client.get(link).content, result.content)
        self.assertEqual(self.engine.calls, 1)
        public = self.client.get("/v1/jobs/"+job, headers={"Authorization": "Bearer " + self.settings.token})
        self.assertNotIn("signature", public.text)
        self.assertNotIn("remote_url", public.text)
        native = self.client.get("/v1/jobs/"+job+"/result", headers={"Authorization": "Bearer " + self.settings.token}).json()
        self.assertIsInstance(native, list); self.assertNotIn("words", native[0]["sentence_info"][0])

    def test_auth_validation_and_unknown_parameters(self):
        self.assertEqual(self.client.post("/api/v1/services/audio/asr/transcription", content=b"invalid").status_code, 401)
        self.assertEqual(self.submit(url="https://evil.example.test/audio").status_code, 400)
        self.assertEqual(self.submit(parameters={"vocabulary_id": "vocab-not-supported"}).status_code, 422)
        self.assertEqual(self.submit(parameters={"diarization_enabled": "false"}).status_code, 422)
        self.assertEqual(self.submit(parameters={"vocabulary": {"术语": True}}).status_code, 422)

    def test_input_hash_deduplicates_signed_url_refresh_and_conflicts(self):
        first = self.submit(key="one", digest=self.digest).json()["output"]["task_id"]
        second = self.submit(key="one", digest=self.digest, url="https://media.example.test/audio?signature=renewed")
        self.assertEqual(second.json()["output"]["task_id"], first)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.submit(key="one", digest="0"*64).status_code, 409)
        self.assertEqual(self.submit(key="one", digest=self.digest, parameters={"vocabulary": {"changed": 5}}).status_code, 409)

    def test_bad_input_and_model_mismatch_never_run_inference(self):
        job = self.submit(digest="0"*64).json()["output"]["task_id"]
        self.worker.run_once()
        self.assertEqual(self.status(job).json()["output"]["results"][0]["code"], "input_integrity_failed")
        job = self.submit().json()["output"]["task_id"]
        with patch.object(self.engine, "identity", return_value={"different": True}): self.worker.run_once()
        self.assertEqual(self.status(job).json()["output"]["results"][0]["code"], "engine_configuration_mismatch")
        self.assertEqual(self.engine.calls, 0)

    def test_retry_cannot_replace_receipt_and_older_worker_cannot_claim(self):
        job = self.submit().json()["output"]["task_id"]
        with self.worker.store.connect() as c:
            self.assertIsNone(c.execute("SELECT id FROM jobs WHERE state='queued' OR (state='running' AND lease_until<0)").fetchone())
        self.worker.store.cancel(job)
        r = self.client.post("/v1/jobs/"+job+"/retry", headers={"Authorization": "Bearer " + self.settings.token})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.worker.store.get(job)["attempt"], 1)

    def test_signed_result_tamper_expiry_and_other_task(self):
        job = self.submit().json()["output"]["task_id"]; self.worker.run_once()
        link = self.status(job).json()["output"]["results"][0]["transcription_url"]
        self.assertEqual(self.client.get(link+"0").status_code, 403)
        other = self.submit().json()["output"]["task_id"]
        self.assertEqual(self.client.get(link.replace(job, other)).status_code, 403)
        with self.worker.store.connect() as c: c.execute("UPDATE jobs SET expires=1 WHERE id=?", (job,))
        self.assertEqual(self.client.get(link).status_code, 410)
        self.assertEqual(self.status(job).status_code, 410)
        self.assertEqual(self.engine.calls, 1)

    def test_empty_speech_has_known_terminal_code(self):
        job = self.submit().json()["output"]["task_id"]; self.engine.text = ""
        self.worker.run_once()
        output = self.status(job).json()["output"]
        self.assertEqual(output["task_status"], "FAILED")
        self.assertEqual(output["results"][0]["code"], "ASR_RESPONSE_HAVE_NO_WORDS")

    def test_link_key_permissions_and_disabled_default(self):
        self.settings.compat_signing_key_file.chmod(0o644)
        with self.assertRaises(ValueError): create_app(self.settings)
        with TestClient(create_app(replace(self.settings, compat_model=""))) as client:
            self.assertEqual(client.get("/api/v1/models", headers={"Authorization":"Bearer "+self.settings.token}).status_code, 503)

    def test_contract_declares_auth_and_retains_untimed_text(self):
        schema = self.client.get("/openapi.json").json()
        path = schema["paths"]["/api/v1/tasks/{job_id}"]["get"]
        self.assertIn("HTTPBearer", path["security"][0])
        self.assertNotIn("security", schema["paths"]["/filetrans-results/{job_id}"]["get"])
        denied = self.client.get("/api/v1/models")
        self.assertEqual(set(denied.json()), {"request_id", "code", "message"})
        self.assertEqual(speech_evidence({}, {"text": "unaligned"})["transcripts"][0]["sentences"],
                         [{"sentence_id": 0, "text": "unaligned"}])

    def test_legacy_schema_upgrade_keeps_original_receipt(self):
        before = self.client.post("/v1/jobs", headers={"Authorization":"Bearer "+self.settings.token},
            files={"files": ("old.wav", self.audio, "audio/wav")}).json()
        self.worker.run_once()
        job = before["id"]
        original = self.worker.store.public(job)
        transcript = self.worker.store.get(job)["result"]
        with self.worker.store.connect() as c:
            for column in ("protocol", "engine", "evidence"):
                c.execute("ALTER TABLE jobs DROP COLUMN " + column)
        reopened = Store(self.settings)
        self.assertEqual(reopened.public(job), original)
        self.assertEqual(reopened.get(job)["result"], transcript)
        self.assertIsNone(reopened.get(job)["protocol"])

    def test_materialized_input_survives_stale_worker_without_second_download(self):
        job = self.submit(digest=self.digest).json()["output"]["task_id"]
        claimed = self.worker.store.claim("interrupted-worker")
        sources = claimed["sources"]
        sources[0].update(self.download(self.settings, sources[0]))
        self.worker.store.materialized(job, "interrupted-worker", sources)
        with self.worker.store.connect() as c: c.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job,))
        self.worker.downloader = download_source
        with patch("sonovect.remote_input.http.client.HTTPSConnection", side_effect=AssertionError("second network download")):
            self.worker.run_once()
        self.assertEqual(self.status(job).json()["output"]["task_status"], "SUCCEEDED")
        self.assertEqual(self.engine.calls, 1)


class RemoteBoundaryTests(unittest.TestCase):
    def download(self, raw, *, maximum=1024, checksum=None):
        class Socket:
            def makefile(self, mode): return io.BytesIO(raw)
        response = http.client.HTTPResponse(Socket())
        response.begin()
        connection = Mock()
        connection.getresponse.return_value = response
        with TemporaryDirectory() as folder, \
                patch("socket.getaddrinfo", return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]), \
                patch("sonovect.remote_input.http.client.HTTPSConnection", return_value=connection) as factory:
            settings = Settings(token="test-only", max_upload_bytes=maximum, compat_input_hosts=("media.example.test",))
            target = Path(folder) / "audio"
            source = {"remote_url":"https://media.example.test/a?private=signature", "path":str(target), "sha256":checksum}
            try:
                result = download_source(settings, source)
                self.assertEqual(target.read_bytes(), b"audio")
                self.assertEqual(result["sha256"], hashlib.sha256(b"audio").hexdigest())
                self.assertEqual(result["size"], 5)
                self.assertEqual(factory.call_args.args[0], "media.example.test")
                self.assertEqual(connection.request.call_args.kwargs["headers"], {"Accept-Encoding":"identity"})
                return result
            finally:
                self.assertFalse(target.with_suffix(".download").exists())
                connection.close.assert_called_once()

    def test_real_http_response_materializes_fixed_and_chunked_bodies(self):
        self.download(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\naudio")
        self.download(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\naudio\r\n0\r\n\r\n")

    def test_redirect_limits_truncation_and_digest_failure_leave_no_partial_file(self):
        for raw, kwargs, error in [
            (b"HTTP/1.1 302 Found\r\nLocation: https://other.test/a\r\nContent-Length: 0\r\n\r\n", {}, "input_download_failed"),
            (b"HTTP/1.1 200 OK\r\nContent-Length: 9999\r\n\r\naudio", {}, "input_limit_exceeded"),
            (b"HTTP/1.1 200 OK\r\n\r\naudio", {"maximum":4}, "input_limit_exceeded"),
            (b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\naudio", {}, "input_download_failed"),
            (b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\naudio", {"checksum":"0"*64}, "input_integrity_failed"),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(MediaError, error):
                self.download(raw, **kwargs)

    def test_exact_https_hosts_only_and_private_resolution_blocked(self):
        hosts = ("media.example.test",)
        for url in ("http://media.example.test/a", "https://media.example.test:444/a",
                    "https://user@media.example.test/a", "https://media.example.test.evil/a"):
            with self.subTest(url=url), self.assertRaises(MediaError): input_url(url, hosts)
        with TemporaryDirectory() as raw:
            settings = Settings(token="test-only", compat_input_hosts=hosts)
            source = {"remote_url":"https://media.example.test/a", "path":str(Path(raw)/"input")}
            with patch("socket.getaddrinfo", return_value=[(2,1,6,'',('127.0.0.1',443))]), self.assertRaisesRegex(MediaError, "input_target_not_allowed"):
                download_source(settings, source)
