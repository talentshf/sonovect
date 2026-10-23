import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('batching', Path(__file__).parents[1]/'qwen-worker/batching.py')
batching = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batching)


class BatchTests(unittest.TestCase):
    def test_file_boundary_is_a_scheduling_boundary(self):
        audios = [([0]*20,10)]*4
        self.assertEqual(list(batching.batch_ranges(audios,['file-0:a','file-0:b','file-1:a','file-1:b'],size=4)),[(0,2),(2,4)])

    def test_long_segments_and_duration_limit_remain_bounded(self):
        audios = [([0]*40,1),([0]*40,1),([0]*100,1),([0]*5,1)]
        self.assertEqual(list(batching.batch_ranges(audios,['file-0:a']*4,size=2,seconds=60)),[(0,1),(1,2),(2,3),(3,4)])

    def test_rolling_history_is_always_sequential(self):
        self.assertEqual(list(batching.batch_ranges([([0],1)]*2,['file-0:a']*2,size=4,rolling=True)),[(0,1),(1,2)])

    def test_invalid_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            list(batching.batch_ranges([([0],1)],[]))
