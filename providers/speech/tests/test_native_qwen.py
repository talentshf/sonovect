import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "qwen-worker/native_runtime.py"
spec = importlib.util.spec_from_file_location("native_qwen", path)
runtime = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


class NativeQwenAlignmentTests(unittest.TestCase):
    def test_preserves_model_classes_including_zero_duration_and_reverse_order(self):
        result = runtime.alignment_items([2, 2, 1, 3], ["one", "two"])
        self.assertEqual([(w.start_time, w.end_time) for w in result.items], [(0.16, 0.16), (0.08, 0.24)])
        # The public boundary validates/rejects these spans; this decoder never repairs them.

    def test_missing_class_does_not_make_up_an_alignment(self):
        self.assertIsNone(runtime.alignment_items([1], ["word"]))


if __name__ == "__main__":
    unittest.main()
