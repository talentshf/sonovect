import importlib.util
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np

PATH = Path(__file__).parents[1] / "vocal-worker/vocal_detector.py"
spec = importlib.util.spec_from_file_location("vocal_detector_under_test", PATH)
vocal = importlib.util.module_from_spec(spec);spec.loader.exec_module(vocal)


class CPUVocalTests(unittest.TestCase):
    def test_missing_or_invalid_speech_handoff_is_not_silence(self):
        for context in [None, {}, {"speech_regions": None}, {"speech_regions": [[False, 100]]},
                        {"speech_regions": [[0, 1001]]}, {"speech_regions": [[100, 20]]}]:
            with self.assertRaises(ValueError):vocal.regions_from_context(context, 1000)

    def test_no_speech_does_not_resolve_download_or_load_any_model(self):
        detector = vocal.VocalDetector()
        detector.load = Mock(side_effect=AssertionError("must not load"))
        result = detector.analyze(np.zeros(16000, dtype=np.float32), {"speech_regions": []})
        detector.load.assert_not_called()
        self.assertEqual(result["emotions"], [])
        self.assertEqual(result["measurements"], [])
        self.assertEqual(result["warnings"], ["no_usable_speech"])

    def test_only_intersecting_windows_run_and_unknown_is_not_renormalized(self):
        detector = vocal.VocalDetector(window_seconds=1)
        detector.load = Mock()
        model = Mock();detector.model = model
        model.generate.return_value = [{"labels": ["angry", "disgusted", "fearful", "happy", "neutral", "other", "sad", "surprised", "unknown"], "scores": [0, 0, 0, 0, .1, 0, 0, 0, .9]}]
        with patch.dict(sys.modules, {"torch": SimpleNamespace(inference_mode=nullcontext)}):
            result = detector.analyze(np.zeros(48000, dtype=np.float32), {"speech_regions": [[1100, 1900]]})
        self.assertEqual(model.generate.call_count, 1)
        self.assertEqual(result["emotions"], [])
        self.assertEqual(result["warnings"], ["emotion_uncertain"])

    def test_inference_failure_clears_resident_model_for_retry(self):
        detector = vocal.VocalDetector();detector.load = Mock();detector.model = Mock()
        detector.model.generate.side_effect = RuntimeError("failure")
        with patch.dict(sys.modules, {"torch": SimpleNamespace(inference_mode=nullcontext)}):
            with self.assertRaises(RuntimeError):detector.analyze(np.zeros(16000, dtype=np.float32), {"speech_regions": [[0, 1000]]})
        self.assertIsNone(detector.model)
