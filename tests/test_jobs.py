import httpx
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import io
import json
import threading
import time
import unittest
import wave
from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.client import Client
from sonovect.config import Settings
from sonovect.models import Options
from sonovect.store import Store
from sonovect.worker import Worker


class Backend:
    def __init__(self):
        self.fail = False
        self.sound_fail = False
    def process(self, path, key, options):
        if self.fail or path.read_bytes() == b"bad":
            raise RuntimeError("private provider URL, credentials and transcript must never appear")
        return ({"key": key, "text": "你好。", "timestamp": [[100, 500]],
                 "sentence_info": [{"text": "你好。", "start": 100, "end": 500, "spk": 0}]},
                {"key": key, "status": "failed" if self.sound_fail else "not_requested", "events": [], "emotions": [], "voice": []})


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temporary.name), token="test-secret-only", backend="speech")
        self.backend = Backend()
        self.worker = Worker(self.settings, self.backend)
        self.client = TestClient(create_app(self.settings))
        self.client.headers["Authorization"] = "Bearer " + self.settings.token
    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()
    def submit(self, contents=(b"audio",), options="{}", key=None):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 1600)
        contents = [buffer.getvalue() if value == b"audio" else value for value in contents]
        return self.client.post("/v1/jobs", files=[("files", ("private-name.wav", b, "audio/wav")) for b in contents],
                                data={"options": options}, headers={"Idempotency-Key": key} if key else {})

    def test_authentication_and_error_details_do_not_echo_input(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        value = self.client.get("/v1/capabilities", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(value.status_code, 401)
        self.assertEqual(value.headers["www-authenticate"], "Bearer")
        value = self.submit(options='{"speakers":"private value"}')
        self.assertEqual(value.status_code, 422)
        self.assertEqual(value.headers["content-type"], "application/problem+json")
        self.assertNotIn("private value", value.text)

    def test_submit_process_reopen_download_and_integrity(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["id"]
        self.assertNotIn("private-name", response.text)
        self.assertNotIn(self.temporary.name, response.text)
        self.assertEqual(self.client.get(f"/v1/jobs/{job_id}/result").status_code, 409)
        self.assertTrue(self.worker.run_once())
        self.assertEqual(Store(self.settings).public(job_id)["status"], "succeeded")
        result = self.client.get(f"/v1/jobs/{job_id}/result")
        self.assertIsInstance(result.json(), list)
        self.assertEqual(result.json()[0]["text"], "你好。")
        manifest = self.client.get(f"/v1/jobs/{job_id}/manifest").json()
        item = manifest["artifacts"][0]
        self.assertEqual(item["sha256"], hashlib.sha256(result.content).hexdigest())
        self.assertEqual(item["size"], len(result.content))
        self.assertEqual(self.client.get(f"/v1/jobs/{job_id}/result?format=text").text, "你好。")
        self.assertIn("00:00:00,100", self.client.get(f"/v1/jobs/{job_id}/result?format=srt").text)

    def test_idempotency_returns_original_and_mismatch_conflicts(self):
        first = self.submit(key="request-one").json()
        same = self.submit(key="request-one")
        self.assertEqual(same.status_code, 200)
        self.assertEqual(same.json()["id"], first["id"])
        self.assertEqual(self.submit((b"different",), key="request-one").status_code, 409)
        self.assertEqual(len(list((Path(self.temporary.name) / "inputs").iterdir())), 1)
        self.assertFalse(list(Path(self.temporary.name).glob("upload-*")))

    def test_partial_batch_and_sound_failure_remain_partial(self):
        job = self.submit((b"audio", b"bad")).json()
        self.worker.run_once()
        value = self.client.get(f"/v1/jobs/{job['id']}").json()
        self.assertEqual(value["status"], "partial")
        self.assertEqual([s["status"] for s in value["sources"]], ["succeeded", "failed"])
        self.assertNotIn("private provider", json.dumps(value))
        self.assertEqual(len(self.client.get(f"/v1/jobs/{job['id']}/result").json()), 1)
        self.backend.sound_fail = True
        job = self.submit().json()
        self.worker.run_once()
        self.assertEqual(self.worker.store.public(job["id"])["status"], "partial")

    def test_idempotency_requires_the_same_explicit_track(self):
        first=self.submit(key="same-request").json()
        self.assertEqual(self.submit(options='{"audio_track":0}',key="same-request").json()["id"],first["id"])
        self.assertEqual(self.submit(options='{"audio_track":1}',key="same-request").status_code,409)

    def test_retry_is_explicit_and_reprocesses_same_inputs(self):
        self.backend.fail = True
        job = self.submit().json()
        self.worker.run_once()
        self.assertEqual(self.worker.store.public(job["id"])["status"], "failed")
        self.backend.fail = False
        response = self.client.post(f"/v1/jobs/{job['id']}/retry")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["attempt"], 2)
        self.worker.run_once()
        self.assertEqual(self.worker.store.public(job["id"])["status"], "succeeded")

    def test_cancel_during_inference_prevents_publication(self):
        entered, released = threading.Event(), threading.Event()
        original = self.backend.process
        def blocking(*args):
            entered.set()
            released.wait(5)
            return original(*args)
        self.backend.process = blocking
        job = self.submit().json()
        with ThreadPoolExecutor() as pool:
            future = pool.submit(self.worker.run_once)
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.client.post(f"/v1/jobs/{job['id']}/cancel").json()["status"], "cancelled")
            self.assertEqual(self.client.post(f"/v1/jobs/{job['id']}/retry").status_code, 409)
            released.set()
            self.assertTrue(future.result())
        self.assertEqual(self.client.get(f"/v1/jobs/{job['id']}/result").status_code, 409)
        self.assertIsNone(self.worker.store.get(job["id"])["result"])

    def test_claim_is_exclusive_and_stale_lease_recovers(self):
        job = self.submit().json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(self.worker.store.claim, [f"worker-{n}" for n in range(6)]))
        self.assertEqual(sum(c is not None for c in claims), 1)
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))
        self.worker.run_once()
        self.assertEqual(self.worker.store.public(job["id"])["status"], "succeeded")

    def test_result_and_input_retention_and_expired_retry(self):
        job = self.submit().json()
        self.worker.run_once()
        row = self.worker.store.get(job["id"])
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET input_expires=0.1 WHERE id=?", (job["id"],))
        self.worker.store.prune()
        self.assertFalse(Path(row["sources"][0]["path"]).exists())
        self.assertEqual(self.client.get(f"/v1/jobs/{job['id']}/result").status_code, 200)
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET expires=0.1 WHERE id=?", (job["id"],))
        self.assertEqual(self.client.get(f"/v1/jobs/{job['id']}/result").status_code, 410)
        self.assertIsNone(self.worker.store.get(job["id"])["result"])

    def test_queue_timing_uses_retry_admission_and_omits_reclaimed_leases(self):
        job = self.submit().json()
        self.worker.store.cancel(job["id"])
        self.worker.store.retry(job["id"])
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET created=?,updated=? WHERE id=?",
                        (time.time() - 3600, time.time() - 0.05, job["id"]))
        claimed = self.worker.store.claim("first")
        self.assertGreaterEqual(claimed["_queue_seconds"], 0.05)
        self.assertLess(claimed["_queue_seconds"], 2)
        self.assertNotIn("_queue_seconds", self.worker.store.public(job["id"]))
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))
        self.assertIsNone(self.worker.store.claim("recovered")["_queue_seconds"])

    def test_client_wait_consumes_completion_events_without_resubmitting(self):
        calls=[]
        def handle(request):
            calls.append((request.method,request.url.path))
            if request.url.path.endswith('/events'):
                return httpx.Response(200,headers={"content-type":"text/event-stream"},text='data: {"type":"job.succeeded"}\n\n')
            return httpx.Response(200,json={"status":"queued" if len(calls)==1 else "succeeded"})
        client=Client(token="test-secret-only",transport=httpx.MockTransport(handle))
        try:
            self.assertEqual(client.wait("test")["status"],"succeeded")
            self.assertEqual(calls,[("GET","/v1/jobs/test"),("GET","/v1/jobs/test/events"),("GET","/v1/jobs/test")])
            for timeout in (0,float("nan"),-1):
                with self.assertRaises(ValueError):client.wait("test",timeout=timeout)
        finally:client.close()


    def test_faster_idle_queue_does_not_repeat_retention_scans(self):
        with patch.object(self.worker.store, "prune", wraps=self.worker.store.prune) as prune:
            for _ in range(10):
                self.assertFalse(self.worker.run_once())
            self.assertEqual(prune.call_count, 1)
        job = self.submit().json()
        with self.assertLogs("sonovect.worker", level="INFO") as logs:
            self.worker.run_once()
        self.assertIn("job_timing", logs.output[-1])
        self.assertNotIn("你好", " ".join(logs.output))
        self.assertNotIn("private-name", " ".join(logs.output))
        # API expiry stays immediate even before the next scheduled cleanup.
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET expires=0.1 WHERE id=?", (job["id"],))
        self.assertEqual(self.client.get(f"/v1/jobs/{job['id']}/result").status_code, 410)

    def test_upload_limits_empty_files_and_unsupported_options(self):
        self.assertEqual(self.submit((b"",)).status_code, 422)
        settings = replace(self.settings, max_upload_bytes=3)
        with TestClient(create_app(settings)) as client:
            value = client.post("/v1/jobs", files={"files": ("x", b"1234")},
                                headers={"Authorization": "Bearer " + settings.token})
            self.assertEqual(value.status_code, 413)
        self.assertFalse(list(Path(self.temporary.name).glob("upload-*")))

    def test_client_exports_exact_manifest_bytes_without_overwrite(self):
        job = self.submit().json()
        self.worker.run_once()
        import httpx
        def handle(request):
            response = self.client.request(request.method, str(request.url), content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        client = Client(token=self.settings.token, transport=httpx.MockTransport(handle))
        try:
            folder = Path(self.temporary.name) / "export"
            manifest = client.export(job["id"], folder)
            for item in manifest["artifacts"]:
                self.assertEqual(hashlib.sha256((folder / item["name"]).read_bytes()).hexdigest(), item["sha256"])
            with self.assertRaises(FileExistsError):
                client.export(job["id"], folder)
        finally:
            client.close()

    def test_retry_preserves_successful_sources_and_attempt_evidence(self):
        calls = []
        original = self.backend.process
        failing = True
        def process(path, key, options):
            calls.append(key)
            if key == "audio_0001" and failing:
                raise RuntimeError("unavailable")
            return original(path, key, options)
        self.backend.process = process
        job_id = self.submit((b"audio", b"audio")).json()["id"]
        self.worker.run_once()
        self.assertEqual(self.worker.store.public(job_id)["status"], "partial")
        failing = False
        self.worker.store.retry(job_id)
        self.worker.run_once()
        self.assertEqual(calls, ["audio_0000", "audio_0001", "audio_0001"])
        attempts = self.client.get(f"/v1/jobs/{job_id}/attempts").json()["attempts"]
        self.assertEqual([a["state"] for a in attempts], ["partial", "succeeded"])
        self.assertEqual(len(attempts[0]["result"]), 1)
        self.assertEqual(len(attempts[1]["result"]), 2)
        self.assertNotIn(self.temporary.name, json.dumps(attempts))

    def test_process_interruption_recovers_saved_sources(self):
        original = self.backend.process
        calls = []
        def process(path, key, options):
            calls.append(key)
            if key == "audio_0001" and len(calls) == 2:
                raise KeyboardInterrupt()
            return original(path, key, options)
        self.backend.process = process
        job_id = self.submit((b"audio", b"audio")).json()["id"]
        with self.assertRaises(KeyboardInterrupt):
            self.worker.run_once()
        self.assertEqual(len(self.worker.store.get(job_id)["result"]), 1)
        with self.worker.store.connect() as con:
            con.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job_id,))
        Worker(self.settings, self.backend).run_once()
        self.assertEqual(calls, ["audio_0000", "audio_0001", "audio_0001"])
        self.assertEqual(self.worker.store.public(job_id)["status"], "succeeded")

    def test_terminal_events_replay_and_notification_retry_do_not_reprocess(self):
        from sonovect.delivery import deliver_one
        import hmac
        settings = replace(self.settings, callback_hosts=("receiver.example",))
        with TestClient(create_app(settings)) as client:
            response = client.post("/v1/jobs", files={"files": ("audio.wav", self._audio())},
                data={"callback_url": "https://receiver.example/completed"},
                headers={"Authorization": "Bearer " + settings.token})
        job_id = response.json()["id"]
        self.worker.run_once()
        calls = []
        def sender(url, body, headers, settings):
            signed = headers["Sonovect-Timestamp"].encode() + b"." + body
            self.assertEqual(headers["Sonovect-Signature"], "v1=" + hmac.new(settings.token.encode(), signed, hashlib.sha256).hexdigest())
            self.assertEqual(json.loads(body)["type"], "job.succeeded")
            self.assertEqual(self.worker.store.public(job_id)["status"], "succeeded")
            calls.append(body)
            return 503 if len(calls) == 1 else 204
        self.assertTrue(deliver_one(self.worker.store, sender))
        self.assertEqual(self.client.get(f"/v1/jobs/{job_id}/notification").json()["state"], "pending")
        self.client.post(f"/v1/jobs/{job_id}/notification/retry")
        self.assertTrue(deliver_one(self.worker.store, sender))
        self.assertEqual(calls[0], calls[1])
        events = self.worker.store.events(job_id)
        response = self.client.get(f"/v1/jobs/{job_id}/events", headers={"Last-Event-ID": str(events[-2]["id"])})
        self.assertIn("event: job.succeeded", response.text)
        self.assertNotIn("event: job.running", response.text)
        self.assertFalse(self.worker.run_once())

    @staticmethod
    def _audio():
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 1600)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
