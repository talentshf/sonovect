"""Run the real diagnostic and VAD dispatch functions without downloading models."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import numpy as np
ROOT=Path(__file__).resolve().parents[1]/'segmentation-worker'


def functions(file,names,namespace):
    tree=ast.parse((ROOT/file).read_text());nodes=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),file,'exec'),namespace)


class DiagnosticTests(unittest.TestCase):
    def test_selected_vad_dispatch_uses_pcm_detect_or_waveform_generate(self):
        env={'np':np,'Any':object,'SAMPLE_RATE':16000,'VAD_BACKEND':'firered',
             'firered_speech_regions':Mock(return_value=[{'start_ms':0,'end_ms':100}])}
        functions('app.py',{'speech_regions','_speech_regions'},env)
        vad=SimpleNamespace(detect=Mock(return_value=({},None)),generate=Mock(return_value=[{'value':[[0,100]]}]))
        model=SimpleNamespace(_vad=vad);audio=np.zeros(1600,dtype=np.float32)
        expected=[{'start_ms':0,'end_ms':100}]
        self.assertEqual(env['speech_regions'](model,audio),expected)
        self.assertEqual(vad.detect.call_args.args[0].dtype,np.int16);vad.generate.assert_not_called()
        env['VAD_BACKEND']='fsmn';self.assertEqual(env['speech_regions'](model,audio),[{**expected[0],'confidence':None}])
        self.assertIs(vad.generate.call_args.kwargs['input'],audio)
        self.assertEqual(vad.generate.call_args.kwargs['fs'],16000)

    def test_silence_one_window_and_invalid_embeddings_return_clear_reports(self):
        model=SimpleNamespace(load=Mock(),speech_regions=Mock(return_value=[]),_embedding=Mock(return_value=np.zeros(2)))
        env={'Path':Path,'Any':object,'np':np,'Models':lambda:model,'SAMPLE_RATE':16000,
             'librosa':SimpleNamespace(load=lambda *a,**k:(np.zeros(16000),16000)),
             'sv_chunk':lambda *a,**k:[]}
        functions('diagnose_speaker_clustering.py',{'diagnose','_cluster_count'},env)
        for segments,status in [([], 'insufficient_speech_windows'),([[0,1]],'insufficient_speech_windows'),
                                ([[0,0.5],[0.5,1]],'invalid_speaker_embeddings')]:
            env['sv_chunk']=lambda *a,**k:segments
            report=env['diagnose'](Path('synthetic.wav'),(0.78,))
            self.assertEqual(report['status'],status);self.assertEqual(report['window_count'],len(segments))
