import importlib.util
from pathlib import Path
import subprocess
import errno
import os
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('gpu_health', Path(__file__).resolve().parents[1] / 'shared/gpu_health.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GPUHealthTests(unittest.TestCase):
    def test_denied_device_is_unhealthy_even_when_present(self):
        with patch.object(module.os, 'open', side_effect=PermissionError()), patch.object(module, '_query') as probe:
            self.assertFalse(module.gpu_health()['available'])
            probe.assert_not_called()

    def test_nvml_failure_and_timeout_are_bounded(self):
        with patch.object(module.os, 'open', return_value=9), patch.object(module.os, 'close'):
            with patch.object(module, '_query', return_value=(255, b'')):
                probe = module.gpu_health()
                self.assertEqual(probe['error'], 'gpu_nvml_unavailable')
            with patch.object(module, '_query', side_effect=subprocess.TimeoutExpired('nvidia-smi', 3)):
                self.assertEqual(module.gpu_health()['error'], 'gpu_probe_timeout')
            with patch.object(module, '_query', return_value=(0, b'610.57.04, NVIDIA GeForce RTX 3090, 24576')):
                self.assertTrue(module.gpu_health()['available'])

    def test_version_mismatch_has_a_distinct_repair_reason(self):
        with patch.object(module.os,'open',return_value=9),patch.object(module.os,'close'),patch.object(module,'_query',return_value=(18,b'Failed to initialize NVML: Driver/library version mismatch')):
            self.assertEqual(module.gpu_health()['error'],'gpu_driver_library_mismatch')


class GPUProbeProcessTests(unittest.TestCase):
    def test_device_errors_do_not_conflate_missing_and_denied(self):
        for number,expected in [(errno.ENOENT,'gpu_device_missing'),(errno.EACCES,'gpu_device_access_denied'),
                                (errno.EPERM,'gpu_device_access_denied'),(errno.EIO,'gpu_probe_failed')]:
            with self.subTest(number=number),patch.object(module.os,'open',side_effect=OSError(number,'fixture')):
                self.assertEqual(module.gpu_health()['error'],expected)
        with patch.object(module.os,'open',return_value=9),patch.object(module.os,'close'),patch.object(module,'_query',side_effect=FileNotFoundError()):
            self.assertEqual(module.gpu_health()['error'],'gpu_probe_tool_missing')

    @unittest.skipUnless(os.name=='posix','POSIX GPU runtime')
    def test_real_subprocess_output_limit_and_timeout_reap_process(self):
        with TemporaryDirectory() as raw:
            root=Path(raw);pid=root/'pid'
            for body,error in [("import sys;sys.stdout.write('x'*20000);sys.stdout.flush();time.sleep(20)",ValueError),
                               ('time.sleep(20)',subprocess.TimeoutExpired)]:
                script = 'import os,time'+chr(10)+'open('+repr(str(pid))+",'w').write(str(os.getpid()))"+chr(10)+body
                original = subprocess.Popen
                started=time.monotonic()
                # Run a real interpreter even when the runtime's /tmp is noexec.
                with patch.object(module.subprocess, 'Popen', side_effect=lambda *a, **kw: original([sys.executable,'-c',script], **kw)), self.assertRaises(error):
                    module._query()
                self.assertLess(time.monotonic()-started,4)
                with self.assertRaises(ProcessLookupError):os.kill(int(pid.read_text()),0)
