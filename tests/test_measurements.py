import copy
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sonovect.api import create_app
from sonovect.assets import main as assets_main
from sonovect.config import Settings
from sonovect.models import Options, measurements_requested
from sonovect.results import acoustic_result
from sonovect.setup import selection, main as setup_main


class MeasurementBoundaryTests(unittest.TestCase):
    def test_measurements_are_strict_and_independent_of_vocal_selection(self):
        self.assertFalse(Options().wire()["measure_voice"])
        self.assertFalse(measurements_requested(Options(analyze_voice=True).wire()))
        self.assertTrue(measurements_requested(Options(measure_voice=True).wire()))
        with self.assertRaises(ValidationError):Options(measure_voice="true")
        with self.assertRaises(ValidationError):Options(measure_voice=None)
        with self.assertRaises(ValidationError):Options(analysis_schema="v2")

    def test_measurements_without_emotion_deployment_and_missing_capability(self):
        with TemporaryDirectory() as tmp:
            settings=Settings(data_dir=Path(tmp), token="numeric-only", measurements_enabled=True, measurements_url="http://measurements", voice_enabled=False)
            with TestClient(create_app(settings)) as c:
                c.headers['Authorization']='Bearer numeric-only'
                cap=c.get('/v1/capabilities').json();self.assertTrue(cap['voice_measurements']);self.assertFalse(cap['voice_analysis'])
                payload={'files':{'files':('a.wav',b'audio')}}
                r=c.post('/v1/jobs',data={'options':json.dumps({'measure_voice':True})},**payload);self.assertEqual(r.status_code,202)
                self.assertEqual(c.post('/v1/jobs',data={'options':json.dumps({'analyze_voice':True})},**payload).status_code,422)
        with TemporaryDirectory() as tmp, TestClient(create_app(Settings(data_dir=Path(tmp),token='numeric-disabled'))) as c:
            c.headers['Authorization']='Bearer numeric-disabled'
            self.assertEqual(c.post('/v1/jobs',files={'files':('a.wav',b'audio')},data={'options':'{"measure_voice":true}'}).status_code,422)

    def payload(self):
        return {'duration_ms':1000,'stage_payloads':{
            'vocal':{'error':'vocal_analysis_failed'},
            'measurements':{'payload':{'parse_valid':True,'measurements_valid':True,
                'engine':{'model':'sonovect/pyin-pcm-rms','revision':'1'},
                'measurements':[dict(kind='relative-energy',value=-20.0,unit='dBFS',method='pcm-rms',status='measured',start_ms=0,end_ms=1000)]}}}}

    def test_model_failure_does_not_remove_numbers_and_numeric_only_skips_vocal(self):
        value=self.payload();before=copy.deepcopy(value)
        both=acoustic_result(value,'a',False,True,True)
        self.assertEqual(both['status'],'partial');self.assertEqual(both['measurements'][0]['value'],-20)
        self.assertEqual(both['stages']['vocal']['status'],'failed')
        only=acoustic_result(value,'a',False,False,True)
        self.assertEqual(only['status'],'completed');self.assertEqual(only['stages']['vocal']['status'],'not_requested')
        self.assertEqual(value,before)

    def test_unrequested_measurement_payload_cannot_leak(self):
        value=acoustic_result(self.payload(),'a',False,False)
        self.assertEqual(value['schema_version'],'audio-analysis-v1')
        self.assertEqual(value['measurements'],[])
        self.assertEqual(value['stages']['measurements']['status'],'not_requested')

    def test_measurement_selection_has_no_additional_model_or_experimental_license(self):
        for route in ['cpu','qwen']:
            base=selection(route=route);numeric=selection(route=route,measurements=True)
            self.assertEqual(base['models'],numeric['models'])
            self.assertEqual(numeric['measurement_model_download_bytes'],0)
            self.assertEqual(numeric['unconfirmed_model_licenses'],[])
            self.assertNotIn('emotion2vec-base',numeric['models'])
            self.assertEqual(numeric['environment']['COMPOSE_PROFILES'],'analysis')

    def test_explicit_emotion_selection_prepares_without_license_ack_but_checks_bytes(self):
        with patch('sonovect.assets.resolve',return_value='selected-cache') as resolve, redirect_stdout(io.StringIO()):
            self.assertEqual(assets_main(['prepare','emotion2vec-base']),0)
            resolve.assert_called_once_with('emotion2vec-base',None,offline=False)
        with patch('sonovect.assets.resolve',side_effect=RuntimeError('model_file_digest_mismatch:model.pt')), redirect_stderr(io.StringIO()):
            self.assertEqual(assets_main(['prepare','emotion2vec-base']),1)
        with TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            path=Path(tmp)/'.env'
            self.assertEqual(setup_main(['--voice','emotion2vec','--write',str(path)]),0)
            self.assertIn('SONOVECT_VOICE_BACKEND=emotion2vec',path.read_text())


if __name__=='__main__':unittest.main()
