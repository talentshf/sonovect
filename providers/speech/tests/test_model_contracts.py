import importlib.util
from pathlib import Path
import unittest
import ast
import json
import re
import tempfile
import hashlib
ROOT=Path(__file__).parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
align=module('speaker_alignment','api/speaker_alignment.py')
model_lock=module('model_lock','segmentation-worker/model_lock.py')
firered_vad=module('firered_vad_adapter','segmentation-worker/firered_vad_adapter.py')

class ModelContractTests(unittest.TestCase):
    def test_firered_vad_explicit_silence_and_millisecond_conversion(self):
        self.assertEqual(firered_vad.speech_regions({'timestamps': []}, 30000), [])
        self.assertEqual(firered_vad.speech_regions({'timestamps': [(12.27, 13.46)]}, 30000),
                         [{'start_ms': 12270, 'end_ms': 13460, 'confidence': None}])
        with self.assertRaisesRegex(ValueError, 'timestamps_invalid'):
            firered_vad.speech_regions({'timestamps': None}, 30000)
    def test_firered_vad_model_bytes_are_pinned(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);(root/'model.pth.tar').write_bytes(b'changed');(root/'cmvn.ark').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'hash_mismatch'):
                firered_vad.verify_model(root)
    def test_mutated_baseline_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw); model=root/'models/iic/test'; model.mkdir(parents=True)
            path=model/'weights.bin';path.write_bytes(b'verified')
            manifest=root/'lock.json';manifest.write_text(json.dumps({'aliases':{'vad':'test'},'models':{'test':{'weights.bin':hashlib.sha256(b'verified').hexdigest()}}}))
            self.assertEqual(model_lock.resolve_pinned_model('vad',root,manifest),str(model))
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'hash_mismatch'):
                model_lock.resolve_pinned_model('vad',root,manifest)
    def test_thinking_reasoning_is_never_an_acoustic_observation(self):
        source = ROOT / 'moss-worker/app.py'
        node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_parse_json')
        namespace = {'json': json, 're': re, 'Any': object}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        parse = namespace['_parse_json']
        self.assertEqual(parse('<think>{"events":["invented"]}</think>{"events":[]}'), {'events': []})
        self.assertEqual(parse('<think>{"events":["invented"]}'), {})
    def test_overlap_does_not_duplicate_or_assign_words_to_one_person(self):
        turns=[dict(start_ms=0,end_ms=3000,speaker='SPK_0'),dict(start_ms=1000,end_ms=2000,speaker='SPK_1')]
        segments=[dict(text='你好，不批准。再讨论。',start_ms=0,end_ms=3000,words=[
            dict(text='你好',start_ms=0,end_ms=900),dict(text='不批准',start_ms=1100,end_ms=1900),dict(text='再讨论',start_ms=2200,end_ms=2800)])]
        result=align.align_speakers(segments,turns)
        self.assertEqual(''.join(r['text'] for r in result),segments[0]['text'])
        self.assertEqual([r['speaker'] for r in result],['SPK_0',None,'SPK_0'])
        self.assertTrue(result[1]['overlap'])
    def test_word_across_a_turn_boundary_is_uncertain_but_not_overlap(self):
        turns=[dict(start_ms=0,end_ms=1000,speaker='SPK_0'),dict(start_ms=1000,end_ms=2000,speaker='SPK_1')]
        self.assertEqual(align.attribution(500,1500,turns),(None,False))
