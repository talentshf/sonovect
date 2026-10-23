import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
spec=importlib.util.spec_from_file_location('gpu_stage',Path(__file__).parents[1]/'shared/gpu_stage.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class StageTests(unittest.TestCase):
    def test_worker_cap_matches_consumer_budget_not_entire_card(self):
        mib=1024**2
        cuda=SimpleNamespace(is_available=lambda:True, mem_get_info=lambda _: (18049*mib,24576*mib),
             set_per_process_memory_fraction=Mock(),reset_peak_memory_stats=Mock(),
             max_memory_allocated=lambda _:7000*mib,max_memory_reserved=lambda _:7600*mib)
        torch=SimpleNamespace(cuda=cuda)
        stage=mod.GPUStage('qwen',8192)
        stage.begin(torch,'cuda:0');stage.finish(torch,'cuda:0')
        self.assertAlmostEqual(cuda.set_per_process_memory_fraction.call_args.args[0],1/3)
        self.assertEqual(stage.status()['last_stage']['peak_reserved_mib'],7600)
        self.assertEqual(stage.status()['admission_authority'],'local-worker')
    def test_large_model_budget_respects_device_reserve(self):
        cuda=SimpleNamespace(is_available=lambda:True,mem_get_info=lambda _: (22000*1024**2,24121*1024**2),
                             set_per_process_memory_fraction=Mock())
        torch=SimpleNamespace(cuda=cuda)
        mod.GPUStage('candidate',20480).configure(torch,'cuda:0')
        with self.assertRaisesRegex(RuntimeError,'exceeds_device'):
            mod.GPUStage('candidate',24576).configure(torch,'cuda:0')
