"""Real media fixtures exercise track choice, subtitle clocks and rejected inputs."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import subprocess
import unittest
import wave
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.media import MediaError, prepare_media
from sonovect.models import Options
from sonovect.worker import Worker


def make_media(path, *inputs, mapping):
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, *mapping, str(path)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.settings = Settings(data_dir=self.root, token="media-test-only")

    def tearDown(self):
        self.temporary.cleanup()

    def test_content_detection_audio_track_and_video_timeline(self):
        path = self.root / "input.audio"  # deliberately no container suffix
        make_media(path, "-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=3",
                   "-itsoffset", "1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                   "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=3",
                   mapping=["-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-f", "matroska"])
        with prepare_media(path, Options().model_dump(), self.settings) as (decoded, media):
            self.assertEqual(media["kind"], "video")
            self.assertEqual(media["audio_tracks"], 2)
            self.assertEqual(media["leading_silence_ms"], 1000)
            self.assertAlmostEqual(media["duration_ms"], 2000, delta=2)
            with wave.open(str(decoded)) as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels()), (16000, 1))
                self.assertEqual(set(audio.readframes(15000)), {0})
                self.assertNotEqual(set(audio.readframes(17000)), {0})
        self.assertFalse(decoded.exists())
        with prepare_media(path, Options(audio_track=1).model_dump(), self.settings) as (decoded, media):
            self.assertEqual(media["audio_track"], 1)
            with wave.open(str(decoded)) as audio:
                self.assertEqual(set(audio.readframes(audio.getnframes())), {0})
        with self.assertRaisesRegex(MediaError, "media_audio_track_unavailable"):
            with prepare_media(path, {"audio_track": 2}, self.settings):
                pass

    def test_corrupt_no_audio_and_duration_limit_are_explicit_failures(self):
        path = self.root / "input.audio"
        path.write_bytes(b"not a media file")
        with self.assertRaisesRegex(MediaError, "media_decode_failed"):
            with prepare_media(path, {}, self.settings):
                pass
        make_media(path, "-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=1",
                   mapping=["-c:v", "ffv1", "-an", "-f", "matroska"])
        with self.assertRaisesRegex(MediaError, "media_no_audio"):
            with prepare_media(path, {}, self.settings):
                pass
        make_media(path, "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
                   mapping=["-f", "wav"])
        with self.assertRaisesRegex(MediaError, "media_duration_exceeded"):
            with prepare_media(path, {}, replace(self.settings, max_media_seconds=0.5)):
                pass
        self.assertFalse(list(self.root.glob("decode-*")))
        with patch("sonovect.media.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaisesRegex(MediaError, "media_decode_timeout"):
                with prepare_media(path, {}, self.settings):
                    pass

    def test_documented_audio_and_video_container_examples_decode(self):
        for container, codec in (("wav", "pcm_s16le"), ("flac", "flac"), ("mp3", "libmp3lame"),
                                 ("ipod", "aac"), ("adts", "aac"), ("ogg", "libopus"), ("aiff", "pcm_s16be")):
            with self.subTest(container=container):
                path = self.root / "audio.input"
                make_media(path, "-f", "lavfi", "-i", "sine=duration=0.1",
                           mapping=["-c:a", codec, "-f", container])
                with prepare_media(path, {}, self.settings) as (_, media):
                    self.assertEqual(media["kind"], "audio")
                    self.assertGreater(media["duration_ms"], 0)
        for container, video_codec, audio_codec in (("mov", "mpeg4", "aac"), ("webm", "libvpx", "libopus"),
                                                    ("avi", "mpeg4", "pcm_s16le")):
            with self.subTest(container=container):
                path = self.root / "video.input"
                make_media(path, "-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=1",
                           "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
                           mapping=["-c:v", video_codec, "-c:a", audio_codec, "-f", container])
                with prepare_media(path, {}, self.settings) as (_, media):
                    self.assertEqual(media["kind"], "video")

    def test_video_through_http_queue_worker_and_original_upload_hash(self):
        path = self.root / "video.mp4"
        make_media(path, "-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=1",
                   "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
                   mapping=["-c:v", "mpeg4", "-c:a", "aac"])
        class Backend:
            def process(self, decoded, key, options):
                with wave.open(str(decoded)) as audio:
                    assert audio.getframerate() == 16000 and audio.getnchannels() == 1
                return {"key": key, "text": ""}, {"key": key, "status": "not_requested", "events": [], "emotions": [], "voice": []}
        with TestClient(create_app(self.settings)) as api:
            api.headers["Authorization"] = "Bearer " + self.settings.token
            response = api.post("/v1/jobs", files={"files": ("wrong.wav", path.read_bytes())})
            job = response.json()
            Worker(self.settings, Backend()).run_once()
            final = api.get(f"/v1/jobs/{job['id']}").json()
            self.assertEqual(final["status"], "succeeded")
            self.assertEqual(final["sources"][0]["media"]["kind"], "video")
            self.assertEqual(final["sources"][0]["sha256"], job["sources"][0]["sha256"])
            self.assertEqual(api.get(f"/v1/jobs/{job['id']}/result").json(), [{"key": "audio_0000", "text": ""}])
            bad = api.post("/v1/jobs", files={"files": ("video.mp4", b"broken")}).json()
            Worker(self.settings, Backend()).run_once()
            self.assertEqual(api.get(f"/v1/jobs/{bad['id']}").json()["sources"][0]["error"], "media_decode_failed")
        self.assertFalse(list(self.root.glob("decode-*")))

    def test_capability_routes_defaults_and_runtime_availability(self):
        with TestClient(create_app(self.settings)) as api:
            value = api.get("/v1/capabilities", headers={"Authorization": "Bearer " + self.settings.token}).json()
            self.assertFalse(value["processing_routes"][-1]["available"])
            self.assertEqual(value["options_schema"]["properties"]["audio_track"]["default"], 0)
            for route in value["processing_routes"]:
                Options.model_validate(route["options"])
            error = api.post("/v1/jobs", headers={"Authorization": "Bearer " + self.settings.token},
                             files={"files": ("a", b"audio")}, data={"options": json.dumps({"analyze_sound": True})})
            self.assertEqual(error.json()["code"], "sound_backend_not_configured")
        for track in (-1, True, "0"):
            with self.assertRaises(ValidationError):
                Options(audio_track=track)


if __name__ == "__main__":
    unittest.main()
