"""Concurrency and idle deadlines of the production MOSS manager."""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class MossIdleTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / 'moss-worker/app.py'
        cls = next(n for n in ast.parse(source.read_text()).body
                   if isinstance(n, ast.ClassDef) and n.name == 'ModelManager')
        self.release = Mock(return_value={'released': True})
        self.pool = Mock(return_value={'reserved_mib': 0})
        namespace = {'time': SimpleNamespace(monotonic=lambda: 301),
                     'IDLE_UNLOAD_SECONDS': 300, 'IDLE_RESERVED_MIB': 256,
                     'allocator_state': self.pool, 'release_idle_cuda': self.release,
                     'torch': object(), 'DEVICE': 'cuda:0'}
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
        self.manager = namespace['ModelManager'].__new__(namespace['ModelManager'])
        self.manager._lock = threading.RLock()
        self.manager._model = object()
        self.manager._processor = object()
        self.manager._busy = False
        self.manager._last_activity = 0

    def test_busy_long_request_and_recent_completion_are_preserved(self):
        self.manager._busy = True
        self.assertIsNone(self.manager.unload(only_if_idle=True))
        self.manager._busy = False
        self.manager._last_activity = 300
        self.assertIsNone(self.manager.unload(only_if_idle=True))
        self.release.assert_not_called()

    def test_idle_model_released_and_repeated_ticks_do_not_repeat_release(self):
        self.assertEqual(self.manager.unload(only_if_idle=True), {'released': True})
        self.assertIsNone(self.manager._model)
        self.assertIsNone(self.manager.unload(only_if_idle=True))
        self.release.assert_called_once()

    def test_pressure_release_and_partial_load_pool_are_cleaned(self):
        self.manager._last_activity = 300
        self.manager.unload()
        self.pool.return_value = {'reserved_mib': 1000}
        self.manager._last_activity = 0
        self.manager.unload(only_if_idle=True)
        self.assertEqual(self.release.call_count, 2)
