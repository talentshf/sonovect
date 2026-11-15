"""Exercise actual loader/processing paths without downloading model weights."""
import ast
import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).parents[1]


class ProcessingOptionsTests(unittest.TestCase):
    def test_vad_only_never_initializes_or_runs_speaker_components(self):
        path = ROOT / "segmentation-worker/app.py"
        cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "Models")
        vad = SimpleNamespace(generate=Mock(return_value=[{"value": [[100, 900]]}]))
        factory = Mock(return_value=vad)
        ns = {"threading": threading, "time": time, "librosa": SimpleNamespace(load=lambda *a, **kw: (np.zeros(16000), 16000)),
              "AutoModel": factory, "VAD_BACKEND": "fsmn", "VAD_MODEL": "fsmn-vad", "MODEL_DEVICE": "cpu",
              "resolve_pinned_model": lambda *a: "vad-path", "os": SimpleNamespace(getenv=lambda *a: "/cache"),
              "pinned_revision": lambda model: "test-revision",
              "SAMPLE_RATE": 16000, "logger": Mock(), "_speech_regions": lambda value, duration: [
                  {"start_ms": 100, "end_ms": 900}],
              "sv_chunk": Mock(side_effect=AssertionError("speaker chunking must be skipped")),
              "ClusterBackend": Mock(side_effect=AssertionError("speaker clustering must not load"))}
        tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
        exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), ns)
        manager = ns["Models"]()
        result = manager.analyze(Path("unused.wav"), speakers=False)
        self.assertEqual(factory.call_count, 1)
        self.assertIsNone(manager._speaker)
        self.assertIsNone(manager._cluster)
        self.assertEqual(result["speech_regions"], [{"start_ms": 100, "end_ms": 900}])
        self.assertEqual(result["speaker_clustering"]["state"], "not_requested")
        manager.analyze(Path("unused.wav"), speakers=False)
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(vad.generate.call_count, 2)

    def test_native_asr_can_load_without_aligner_and_add_it_once(self):
        path = ROOT / "qwen-worker/native_runtime.py"
        spec = importlib.util.spec_from_file_location("processing_native_runtime", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        asr, aligner, processor = Mock(), Mock(), Mock()
        deps = SimpleNamespace(AutoProcessor=processor, Qwen3ASRForConditionalGeneration=asr,
                               Qwen3ASRForTokenClassification=aligner)
        with patch.dict(sys.modules, {"transformers": deps}):
            runtime = module.NativeQwenASR.from_pretrained("asr", dtype="bf16", device_map="cpu",
                max_inference_batch_size=1, max_new_tokens=16, forced_aligner=None, forced_aligner_kwargs={})
            asr.from_pretrained.assert_called_once()
            aligner.from_pretrained.assert_not_called()
            self.assertIsNone(runtime.aligner)
            runtime.load_aligner("aligner", {"device_map": "cpu"})
            runtime.load_aligner("aligner", {"device_map": "cpu"})
            aligner.from_pretrained.assert_called_once()
            asr.from_pretrained.assert_called_once()
