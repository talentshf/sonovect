import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gpu_capacity", Path(__file__).parents[1] / "shared/gpu_capacity.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CapacityTests(unittest.TestCase):
    def test_waits_for_other_service_release(self):
        now, waiting = [0], []
        def sleep(seconds): now[0] += seconds
        def memory(): return (0 if now[0] < 300 else 10, 24)
        module.wait_for_capacity(memory, 6, clock=lambda: now[0], sleep=sleep, on_wait=waiting.append)
        self.assertEqual(now[0], 300)
        self.assertFalse(waiting[-1])

    def test_wait_is_bounded_and_clears_state(self):
        now, waiting = [0], []
        def sleep(seconds): now[0] += seconds
        with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
            module.wait_for_capacity(lambda: (0, 24), 6, timeout=5, clock=lambda: now[0], sleep=sleep, on_wait=waiting.append)
        self.assertEqual(now[0], 5)
        self.assertFalse(waiting[-1])

    def test_gpu_errors_are_not_misreported_as_capacity(self):
        def memory(): raise ValueError("driver error")
        with self.assertRaises(ValueError):
            module.wait_for_capacity(memory, 6)


if __name__ == "__main__":
    unittest.main()
