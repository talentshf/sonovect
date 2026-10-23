"""Exercise the documented Skill/CLI workflow against the real job API/store.

Only model inference is replaced; this is an interface regression, not an
accuracy evaluation.
"""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
import httpx
from sonovect.api import create_app
from sonovect.cli import main
from sonovect.client import Client
from sonovect.config import Settings
from sonovect.worker import Worker


class SpeechOnly:
    def process(self, path, key, options):
        return ({"key": key, "text": "Hello.", "timestamp": [[0, 500]],
                 "sentence_info": [{"text": "Hello.", "start": 0, "end": 500, "spk": 0}]},
                {"key": key, "status": "not_requested", "events": [], "emotions": [], "voice": []})


class CLIWorkflowTests(unittest.TestCase):
    def test_submission_polling_layers_formats_and_verified_export(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = Settings(data_dir=root / "state", token="cli-fixture-token", backend="funasr")
            worker = Worker(settings, SpeechOnly())
            audio = root / "input.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 8000)
            with TestClient(create_app(settings)) as api:
                def handle(request):
                    response = api.request(request.method, str(request.url), content=request.content,
                                           headers=dict(request.headers))
                    return httpx.Response(response.status_code, content=response.content, headers=response.headers)

                def invoke(*args):
                    out, err = StringIO(), StringIO()
                    with patch("sonovect.cli.Client", side_effect=lambda: Client(
                            token=settings.token, transport=httpx.MockTransport(handle))), \
                            redirect_stdout(out), redirect_stderr(err):
                        code = main(list(args))
                    self.assertEqual(code, 0, err.getvalue())
                    return out.getvalue()

                self.assertEqual(json.loads(invoke("capabilities"))["version"], "0.1.0")
                job = json.loads(invoke("submit", str(audio), "--idempotency-key", "cli-flow"))
                self.assertEqual(job["status"], "queued")
                self.assertTrue(worker.run_once())
                worker.announce()
                self.assertEqual(json.loads(invoke("wait", job["id"], "--timeout", "1"))["status"], "succeeded")
                self.assertEqual(json.loads(invoke("ready"))["status"], "ready")
                same = json.loads(invoke("submit", str(audio), "--idempotency-key", "cli-flow"))
                self.assertEqual(same["id"], job["id"])
                result = json.loads(invoke("result", job["id"]))
                self.assertEqual(result[0]["text"], "Hello.")
                self.assertNotIn("measurements", result[0])
                self.assertEqual(invoke("result", job["id"], "--format", "text"), "Hello.")
                self.assertIn("00:00:00,000 --> 00:00:00,500", invoke("result", job["id"], "--format", "srt"))
                analysis = json.loads(invoke("analysis", job["id"]))
                self.assertEqual(analysis[0]["status"], "not_requested")
                manifest = json.loads(invoke("export", job["id"], str(root / "export")))
                self.assertTrue(manifest["artifacts"])
                self.assertEqual(json.loads((root / "export/result.json").read_text()), result)


if __name__ == "__main__":
    unittest.main()
