from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import httpx
from sonovect.backends import BackendError, FunASRBackend, SpeechBackend
from sonovect.config import Settings
from sonovect.models import Options


class BackendTests(unittest.TestCase):
    def test_offline_native_uses_cache_api_and_propagates_missing_cache(self):
        from sonovect.backends import native_model_source
        snapshot = Mock(return_value="/local-model-cache")
        modules = {
            "funasr.download.name_maps_from_hub": SimpleNamespace(name_maps_ms={"paraformer-zh": "official/model"}),
            "modelscope": SimpleNamespace(snapshot_download=snapshot),
        }
        with patch.dict("os.environ", {"MODELSCOPE_OFFLINE": "1"}), patch.dict("sys.modules", modules), \
                patch("sonovect.assets.verify", side_effect=lambda p, m: p):
            self.assertEqual(native_model_source("paraformer-zh", "v2.0.4"), "/local-model-cache")
            self.assertEqual(snapshot.call_args.args[0], "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
            self.assertTrue(snapshot.call_args.kwargs["local_files_only"])
            snapshot.side_effect = FileNotFoundError("cache missing")
            with self.assertRaises(FileNotFoundError):
                native_model_source("fsmn-vad", "v2.0.4")

    def test_malformed_acoustic_stage_preserves_successful_transcript(self):
        payload = {"text": "Valid speech.", "segments": [{"text": "Valid speech.", "start_ms": 0, "end_ms": 100}],
                   "enrichment": {"lanes": {"speech": {"state": "completed"}, "acoustic": {"state": "completed"}},
                                  "acoustic_analysis": {"events": [{"label": "rain", "start_ms": -10, "end_ms": 100}]}}}
        response = httpx.Response(200, request=httpx.Request("POST", "http://provider/transcribe/full"), json=payload)
        with TemporaryDirectory() as raw:
            path = Path(raw) / "audio.wav"
            path.write_bytes(b"audio")
            with patch("sonovect.backends.httpx.Client") as client:
                client.return_value.__enter__.return_value.post.return_value = response
                result, analysis = SpeechBackend(Settings(token="backend-test", backend="speech")).process(
                    path, "a", Options(analyze_sound=True).model_dump())
            self.assertEqual(result["text"], "Valid speech.")
            self.assertEqual(analysis["status"], "failed")

    def test_native_generate_is_called_and_result_is_not_rewritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.wav"
            path.write_bytes(b"audio")
            native = [{"key": str(path), "text": "你好。", "timestamp": [[100, 300]],
                       "sentence_info": [{"text": "你好。", "start": 100, "end": 300, "spk": 3}]}]
            model = Mock()
            model.generate.return_value = native
            factory = Mock(return_value=model)
            with patch.dict("os.environ", {"MODELSCOPE_OFFLINE": "0"}), \
                    patch("sonovect.backends.native_model_source", side_effect=lambda name, revision: name), \
                    patch.dict("sys.modules", {"funasr": SimpleNamespace(AutoModel=factory)}):
                backend = FunASRBackend(Settings(token="backend-test"))
                result, analysis = backend.process(path, "audio_0000", Options().model_dump())
                backend.process(path, "audio_0001", Options(hotwords=["术语"]).model_dump())
            self.assertEqual(factory.call_count, 1)
            self.assertFalse(factory.call_args.kwargs["trust_remote_code"])
            self.assertEqual(model.generate.call_args.kwargs["hotword"], "术语")
            self.assertEqual(result["sentence_info"], native[0]["sentence_info"])
            self.assertEqual(analysis["status"], "not_requested")

    def test_provider_http_200_with_speech_lane_failure_is_failure(self):
        class Provider:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, url, **kwargs):
                return httpx.Response(200, request=httpx.Request("POST", url), json={
                    "text": "", "enrichment": {"lanes": {"speech": {"state": "failed"}}}})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.wav"
            path.write_bytes(b"audio")
            with patch("sonovect.backends.httpx.Client", Provider):
                with self.assertRaises(BackendError):
                    SpeechBackend(Settings(token="backend-test", backend="speech")).process(path, "a", Options().model_dump())

    def test_native_optional_transport_failure_is_diagnosable_without_logging_payload(self):
        with TemporaryDirectory() as raw:
            path=Path(raw)/'input.wav';path.write_bytes(b'private-audio-bytes')
            model=Mock();model.generate.return_value=[dict(text='保留语音。')]
            response=httpx.Response(500,request=httpx.Request('POST','http://voice/analyze'),
                                    json={'detail':'private generated description'})
            backend=FunASRBackend(Settings(token='backend-test',voice_enabled=True,voice_url='http://voice'))
            backend.models[True]=model
            with patch.dict('sys.modules',{'funasr':SimpleNamespace(AutoModel=Mock())}), \
                    patch('sonovect.backends.httpx.Client') as client, self.assertLogs('sonovect.backends',level='ERROR') as logs:
                client.return_value.__enter__.return_value.post.return_value=response
                result,analysis=backend.process(path,'audio_0000',Options(analyze_voice=True).model_dump())
            self.assertEqual(result['text'],'保留语音。')
            self.assertEqual(analysis['stages']['vocal']['error'],'vocal_analysis_failed')
            log='\n'.join(logs.output)
            self.assertIn('stage=vocal',log);self.assertIn('upstream_status=500',log)
            self.assertNotIn('private-audio-bytes',log);self.assertNotIn('private generated description',log)


if __name__ == "__main__":
    unittest.main()
