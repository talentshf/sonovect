"""Use the unmodified OpenAI client over real admission, queue, worker and media decoding."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import unittest
import wave

from fastapi.testclient import TestClient
from openai import OpenAI

from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.store import Store
from sonovect.worker import Worker
from sonovect.recognition import Recognition


def audio_bytes():
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 1600)
    return buffer.getvalue()


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def process(self, path, key, options):
        self.calls.append(options)
        return ({"key": key, "text": "你好，世界。"},
                {"key": key, "status": "not_requested", "events": [], "emotions": [], "voice": []})


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), token="test-standard-only", backend="speech", sync_timeout=2)
        self.backend = RecordingBackend()
        self.worker = Worker(self.settings, self.backend)
        self.stopping = threading.Event()
        def run():
            while not self.stopping.is_set():
                if not self.worker.run_once():
                    self.stopping.wait(.01)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        self.http = TestClient(create_app(self.settings))
        self.http.headers["Authorization"] = "Bearer " + self.settings.token
        self.sdk = OpenAI(base_url="http://testserver/v1", api_key=self.settings.token,
                          max_retries=0, http_client=self.http, _strict_response_validation=True)

    def tearDown(self):
        self.stopping.set()
        self.thread.join(5)
        self.sdk.close()
        self.temp.cleanup()

    def request(self, **fields):
        return self.http.post("/v1/audio/transcriptions", files={"file": ("voice.wav", audio_bytes(), "audio/wav")},
                              data={"model": self.settings.transcription_model, **fields})

    def test_unmodified_sdk_models_json_and_text_skip_optional_stages(self):
        self.assertEqual(self.sdk.models.list().data[0].id, "qwen3-asr")
        result = self.sdk.audio.transcriptions.create(model="qwen3-asr", file=("voice.wav", audio_bytes()),
                                                       prompt="通话讨论术语", response_format="json")
        self.assertEqual(result.text, "你好，世界。")
        text = self.sdk.audio.transcriptions.create(model="qwen3-asr", file=("voice.wav", audio_bytes()), response_format="text")
        self.assertEqual(text, "你好，世界。")
        for options in self.backend.calls:
            self.assertFalse(options["speakers"])
            self.assertEqual(options["timestamps"], "none")
            self.assertFalse(options["analyze_sound"])
        self.assertEqual(self.backend.calls[0]["context"], "通话讨论术语")
        self.assertIsNone(self.backend.calls[0]["language"])

    def test_idempotent_retry_uses_one_task_and_one_inference(self):
        def submit(prompt=""):
            return self.sdk.audio.transcriptions.with_raw_response.create(
                model="qwen3-asr", file=("voice.wav", audio_bytes()), prompt=prompt,
                extra_headers={"Idempotency-Key": "same-voice"})
        first, second = submit(), submit()
        self.assertEqual(first.headers["x-sonovect-job-id"], second.headers["x-sonovect-job-id"])
        self.assertEqual(len(self.backend.calls), 1)
        from openai import ConflictError
        with self.assertRaises(ConflictError):
            submit("changed-context")

    def test_unsupported_requests_fail_before_creating_a_job(self):
        for fields in ({"model": "whisper-1"}, {"stream": "true", "response_format": "text"}, {"response_format": "verbose_json"},
                       {"temperature": "1"}, {"speakers": "true"}, {"timestamp_granularities[]": "word"}):
            with self.subTest(fields=fields):
                response = self.request(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        with self.worker.store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_timeout_keeps_original_job_recoverable(self):
        self.stopping.set()
        self.thread.join(5)
        http = TestClient(create_app(replace(self.settings, sync_timeout=.02)))
        with http:
            response = http.post("/v1/audio/transcriptions", files={"file": ("voice.wav", audio_bytes())},
                                 data={"model": "qwen3-asr"}, headers={"Authorization": "Bearer " + self.settings.token})
        self.assertEqual(response.status_code, 408)
        self.assertEqual(response.headers["x-should-retry"], "false")
        job_id = response.headers["x-sonovect-job-id"]
        self.assertEqual(self.worker.store.public(job_id)["status"], "queued")
        self.assertTrue(self.worker.run_once())
        self.assertEqual(Store(self.settings).get(job_id)["result"][0]["text"], "你好，世界。")

    def test_boundary_authentication_has_standard_error_shape(self):
        response = self.http.post("/v1/audio/transcriptions", content=b"not parsed",
                                  headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_sdk_word_and_diarized_results_use_actual_evidence(self):
        def process(path, key, options):
            self.backend.calls.append(options)
            transcript = {"key": key, "text": "你好。", "sentence_info": [{"text": "你好。", "start": 10, "end": 80, "spk": 0}]}
            evidence = {"language": "Chinese", "transcripts": [{"text": "你好。", "sentences": [
                {"text": "你好。", "words": [{"text": "你好", "begin_time": 10, "end_time": 80}]}]}]}
            return Recognition(transcript, {"key": key, "status": "not_requested"}, evidence)
        self.backend.process = process
        words = self.sdk.audio.transcriptions.create(model="qwen3-asr", file=("voice.wav", audio_bytes()),
            response_format="verbose_json", timestamp_granularities=["word"])
        self.assertEqual(words.words[0].start, .01)
        self.assertEqual(words.words[0].word, "你好")
        self.assertIsNone(words.segments)
        speakers = self.sdk.audio.transcriptions.create(model="qwen3-asr", file=("voice.wav", audio_bytes()), response_format="diarized_json")
        self.assertEqual(speakers.segments[0].speaker, "speaker_0")
        self.assertTrue(self.backend.calls[-1]["speakers"])
        self.assertEqual(self.backend.calls[-1]["timestamps"], "word")

    def test_unavailable_word_alignment_keeps_successful_transcription(self):
        response = self.request(response_format="verbose_json", **{"timestamp_granularities[]": "word"})
        self.assertEqual(response.status_code, 422)
        job_id = response.headers["x-sonovect-job-id"]
        self.assertEqual(self.worker.store.get(job_id)["result"][0]["text"], "你好，世界。")

    def test_analysis_only_task_does_not_publish_a_fake_empty_transcript(self):
        def process(path, key, options):
            self.assertFalse(options["transcribe"])
            return Recognition(None, {"key": key, "status": "completed", "stages": {"speech_activity": {"status": "completed"}},
                "speech_regions": [{"start_ms": 10, "end_ms": 80}]}, {})
        self.backend.process = process
        response = self.http.post("/v1/jobs", files={"files": ("voice.wav", audio_bytes())},
                                  data={"options": json.dumps({"transcribe": False, "detect_speech": True})})
        job_id = response.json()["id"]
        deadline = __import__('time').monotonic() + 3
        while self.worker.store.public(job_id)["status"] not in {"succeeded", "failed"}:
            self.assertLess(__import__('time').monotonic(), deadline)
            __import__('time').sleep(.01)
        self.assertEqual(self.worker.store.public(job_id)["status"], "succeeded")
        self.assertEqual(self.http.get(f"/v1/jobs/{job_id}/result").status_code, 409)
        self.assertEqual(self.http.get(f"/v1/jobs/{job_id}/analysis").json()[0]["speech_regions"][0]["start_ms"], 10)

    def test_sdk_stream_forwards_processing_events_and_matches_persisted_text(self):
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        original = self.backend.process
        def process(path, key, options, progress):
            progress({"source_index": 0, "text": "你好，", "processed_until_ms": 50})
            entered.set()
            release.wait(3)
            progress({"source_index": 0, "text": "你好，世界。", "processed_until_ms": 100})
            return original(path, key, options)
        self.backend.process_stream = process
        def consume():
            return list(self.sdk.audio.transcriptions.create(model="qwen3-asr", file=("voice.wav", audio_bytes()), stream=True))
        with ThreadPoolExecutor() as pool:
            future = pool.submit(consume)
            self.assertTrue(entered.wait(2))
            with self.worker.store.connect() as con:
                job_id = con.execute("SELECT id FROM jobs").fetchone()[0]
            self.assertIsNone(self.worker.store.get(job_id)["result"])
            self.assertIn("transcript.partial", [e["type"] for e in self.worker.store.events(job_id)])
            release.set()
            events = future.result(3)
        self.assertEqual("".join(e.delta for e in events if e.type == "transcript.text.delta"), "你好，世界。")
        self.assertEqual(events[-1].type, "transcript.text.done")
        self.assertEqual(events[-1].text, self.worker.store.get(job_id)["result"][0]["text"])
