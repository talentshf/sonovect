"""A peer can consume GPU memory while immutable snapshots are verified."""
import ast
import importlib.util
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('load_capacity_wait', ROOT/'shared/gpu_capacity.py')
capacity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capacity)


class LoadCapacityTests(unittest.TestCase):
    def load_method(self, worker, explicit=False, unavailable=False):
        source = ROOT/(worker+'-worker/app.py')
        class_name = 'ModelManager' if worker == 'moss' else 'LazyModelManager'
        cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == class_name)
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'load')
        events = []
        state = dict(free=21, clock=0)
        def verified(*args, **kwargs):
            events.append('verify')
            state['free'] = 15  # An independent peer loaded during hashing.
            return '/verified'
        def release_peer(seconds):
            state['clock'] += seconds
            events.append('peer_release')
            if not unavailable:state['free'] = 21
        def require():
            events.append('capacity')
            capacity.wait_for_capacity(lambda: (state['free'], 24), 20, timeout=2,
                clock=lambda: state['clock'], sleep=release_peer)
        def allocate(*args, **kwargs):
            events.append('allocate')
            self.assertGreaterEqual(state['free'], 20)
            return SimpleNamespace(eval=lambda: None)
        model = Mock(side_effect=allocate)
        namespace = dict(time=SimpleNamespace(monotonic=lambda: 0, time=lambda: 0),
            torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, empty_cache=Mock())),
            DEVICE='cuda:0', os=os, logger=Mock(), snapshot_download=Mock(),
            _require_gpu_capacity=require, resolve_pinned_snapshot=verified,
            MODEL_ID='model', MODEL_REVISION='revision', ALIGNER_ID='aligner', ALIGNER_REVISION='revision',
            MossAudioModel=SimpleNamespace(from_pretrained=model),
            Qwen2Tokenizer=SimpleNamespace(from_pretrained=Mock()),
            MossAudioProcessor=Mock(), _dtype=lambda: 'bfloat16',
            ATTENTION_IMPLEMENTATION='auto', MAX_BATCH_SIZE=1, MAX_NEW_TOKENS=768)
        tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
        exec(compile(ast.fix_missing_locations(tree), str(source), 'exec'), namespace)
        manager=SimpleNamespace(_lock=threading.RLock(), _model=None, _processor=None,
            _stage=SimpleNamespace(configure=Mock()), _load_count=0)
        modules={'sonovect_assets': SimpleNamespace(verify_identity=verified),
                 'native_runtime': SimpleNamespace(NativeQwenASR=SimpleNamespace(from_pretrained=model))}
        env={'MOSS_MODEL_ROOT':'/explicit'} if explicit else {}
        with patch.dict(os.environ, env, clear=True), patch.dict('sys.modules', modules):
            if unavailable:
                with self.assertRaisesRegex(RuntimeError, 'GPU capacity temporarily unavailable'):
                    namespace['load'](manager)
                model.assert_not_called()
                self.assertIsNone(manager._model)
            else:
                namespace['load'](manager)
                model.assert_called_once()
        return events

    def test_moss_checks_after_verified_cache_and_waits_for_peer(self):
        events=self.load_method('moss')
        self.assertEqual(events, ['verify','capacity','peer_release','allocate'])

    def test_moss_explicit_root_has_same_current_capacity_gate(self):
        events=self.load_method('moss', explicit=True)
        self.assertEqual(events, ['verify','capacity','peer_release','allocate'])

    def test_qwen_checks_after_both_snapshots_and_waits_for_peer(self):
        events=self.load_method('qwen')
        self.assertEqual(events, ['verify','verify','capacity','peer_release','allocate'])

    def test_unavailable_capacity_never_allocates_or_claims_loaded(self):
        for worker in ['moss','qwen']:
            with self.subTest(worker=worker):self.load_method(worker, unavailable=True)

