import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('gpu_health', Path(__file__).resolve().parents[1] / 'shared/gpu_health.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GPUHealthTests(unittest.TestCase):
    def test_denied_device_is_unhealthy_even_when_present(self):
        with patch.object(module.os, 'open', side_effect=PermissionError()), patch.object(module.subprocess, 'run') as probe:
            self.assertFalse(module.gpu_health()['available'])
            probe.assert_not_called()

    def test_nvml_failure_and_timeout_are_bounded(self):
        with patch.object(module.os, 'open', return_value=9), patch.object(module.os, 'close'):
            with patch.object(module.subprocess, 'run', return_value=Mock(returncode=255, stdout=b'', stderr=b'')):
                probe = module.gpu_health()
                self.assertEqual(probe['error'], 'gpu_nvml_unavailable')
            with patch.object(module.subprocess, 'run', side_effect=subprocess.TimeoutExpired('nvidia-smi', 3)):
                self.assertEqual(module.gpu_health()['error'], 'gpu_probe_timeout')
            with patch.object(module.subprocess, 'run', return_value=Mock(returncode=0, stdout=b'610.57.04, NVIDIA GeForce RTX 3090, 24576')):
                self.assertTrue(module.gpu_health()['available'])

    def test_version_mismatch_has_a_distinct_repair_reason(self):
        with patch.object(module.os,'open',return_value=9),patch.object(module.os,'close'),patch.object(module.subprocess,'run',return_value=Mock(returncode=18,stdout=b'',stderr=b'Failed to initialize NVML: Driver/library version mismatch')):
            self.assertEqual(module.gpu_health()['error'],'gpu_driver_library_mismatch')
