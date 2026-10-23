"""Exercise the real manager without importing CUDA/model packages on the Mac."""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
import importlib.util
from unittest.mock import Mock


class QwenIdleTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / "qwen-worker/app.py"
        tree = ast.parse(source.read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LazyModelManager")
        self.clock = SimpleNamespace(monotonic=Mock(return_value=301), time=Mock(return_value=1000))
        self.cuda = SimpleNamespace(is_available=Mock(return_value=True), empty_cache=Mock())
        namespace = {"time": self.clock, "IDLE_UNLOAD_SECONDS": 300, "logger": Mock(),
                     "gc": Mock(), "torch": self.cuda, "threading": threading, "DEVICE": "cuda:0"}
        namespace["torch"] = SimpleNamespace(cuda=self.cuda)
        spec = importlib.util.spec_from_file_location('batching', source.with_name('batching.py'))
        batching = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batching)
        namespace.update(MAX_BATCH_SIZE=2, MAX_BATCH_AUDIO_SECONDS=60, ROLLING_CONTEXT_CHARS=0,
                         ASR_BACKEND='qwen', batch_ranges=batching.batch_ranges,
                         checked_results=batching.checked_results)
        compiled = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
        exec(compile(ast.fix_missing_locations(compiled), str(source), "exec"), namespace)
        self.namespace = namespace
        self.manager = namespace["LazyModelManager"].__new__(namespace["LazyModelManager"])
        self.manager._stage = Mock()
        self.manager._lock = threading.RLock()
        self.manager._model = object()
        self.manager._busy = False
        self.manager._last_activity = 0
        self.manager._loaded_at = 1
        self.manager._needs_cleanup = False
        self.manager._batch_fallbacks = 0

    def test_release_after_deadline(self):
        self.assertTrue(self.manager.unload(only_if_idle=True))
        self.assertIsNone(self.manager._model)
        self.cuda.empty_cache.assert_called_once()

    def test_new_task_completion_invalidates_old_timer_decision(self):
        self.manager._last_activity = 300
        self.assertFalse(self.manager.unload(only_if_idle=True))
        self.assertIsNotNone(self.manager._model)

    def test_active_long_task_is_never_reaped(self):
        self.manager._busy = True
        self.assertFalse(self.manager.unload(only_if_idle=True))

    def test_partial_load_allocations_are_cleaned_without_a_model(self):
        self.manager._model = None
        self.manager._needs_cleanup = True
        self.assertTrue(self.manager.unload(only_if_idle=True))
        self.cuda.empty_cache.assert_called_once()
        self.assertFalse(self.manager._needs_cleanup)

    def test_failed_request_resets_idle_clock_and_busy(self):
        self.manager.load = Mock(side_effect=RuntimeError("failed load"))
        with self.assertRaises(RuntimeError):
            self.manager._transcribe_batch([], [], [], [])
        self.assertFalse(self.manager._busy)
        self.assertEqual(self.manager._last_activity, 301)

    def test_local_chunks_preserve_rolling_context(self):
        self.namespace['ROLLING_CONTEXT_CHARS']=240
        self.manager._admission_lock=threading.Lock()
        self.manager._transcribe_batch=Mock(side_effect=[[SimpleNamespace(text='previous words')],[SimpleNamespace(text='next words')]])
        result=self.manager.transcribe([([0],1),([0],1)],['en','en'],['terms','terms'],['speaker','speaker'])
        self.assertEqual(len(result),2)
        self.assertIn('previous words',self.manager._transcribe_batch.call_args_list[1].args[2][0])
        self.assertFalse(self.manager._waiting_for_gpu)

    def test_microbatch_preserves_order_language_context_and_timestamps(self):
        self.manager.load = Mock()
        expected = [SimpleNamespace(text='first'), SimpleNamespace(text='second')]
        model = SimpleNamespace(transcribe=Mock(return_value=expected))
        self.manager._model = model
        audios = [([0]*10,10), ([0]*20,10)]
        self.assertEqual(self.manager._transcribe_batch(audios,['Chinese','English'],['one','two'],['file-0:a','file-0:b']),expected)
        self.assertEqual(model.transcribe.call_args.kwargs, {
            'audio':audios,'context':['one','two'],'language':['Chinese','English'],'return_time_stamps':True})

    def test_batch_result_count_mismatch_is_not_silently_truncated(self):
        self.manager.load = Mock()
        self.manager._model = SimpleNamespace(transcribe=Mock(return_value=[]))
        with self.assertRaisesRegex(RuntimeError,'asr_result_count_mismatch'):
            self.manager._transcribe_batch([([0],1)],['Chinese'],[''],['file-0:a'])
        self.assertFalse(self.manager._busy)

    def test_oom_retries_individual_segments_under_the_same_stage(self):
        class OOM(Exception): pass
        self.cuda.OutOfMemoryError = OOM
        self.manager.load = Mock()
        expected = [SimpleNamespace(text='a'), SimpleNamespace(text='b')]
        model = SimpleNamespace(transcribe=Mock(side_effect=[OOM(),[expected[0]],[expected[1]]]))
        self.manager._model = model
        result = self.manager._transcribe_batch([([0],1),([0],1)],['Chinese']*2,['']*2,['file-0:a']*2)
        self.assertEqual(result,expected)
        self.assertEqual(self.manager._batch_fallbacks,1)
        self.manager._stage.begin.assert_called_once()
        self.manager._stage.finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
