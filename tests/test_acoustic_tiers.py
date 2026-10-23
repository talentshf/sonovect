import json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.models import Analysis,Options
from sonovect.results import acoustic_result
from sonovect.setup import selection

ENGINE={"model":"test/model","revision":"fixed"}
def envelope(event=None,vocal=None):return {"duration_ms":1000,"stage_payloads":{"events":{"payload":event},"vocal":{"payload":vocal}}}
def events():return {"engine":ENGINE,"parse_valid":True,"events_valid":True,"events":[{"label":"Rain","start_ms":0,"end_ms":1000}]}
def vocal():return {"engine":ENGINE,"parse_valid":True,"vocal_valid":True,"emotions":[{"label":"NEUTRAL"}],"voice":[{"label":"low","kind":"pitch","start_ms":0,"end_ms":1000}]}
class AcousticTiersTests(unittest.TestCase):
 def test_optional_stage_failure_retains_other_stage_and_speech_contract(self):
  for e,v,field in [(events(),None,'events'),(None,vocal(),'voice')]:
   x=acoustic_result(envelope(e,v),'a',True,True);Analysis.model_validate(x)
   self.assertEqual(x['status'],'partial');self.assertTrue(x[field]);self.assertEqual(len(x['engines']),1)
  x=acoustic_result(envelope(events(),vocal()),'a',True,True)
  self.assertEqual(x['status'],'completed');self.assertEqual(x['voice'][0]['kind'],'pitch')
 def test_bad_optional_observation_does_not_discard_valid_sibling(self):
  v=vocal();v['voice'][0]['start_ms']=-1
  x=acoustic_result(envelope(events(),v),'a',True,True)
  self.assertEqual(x['status'],'partial');self.assertEqual(x['voice'],[]);self.assertEqual(x['events'][0]['label'],'Rain')
 def test_unrequested_stage_payload_is_never_published(self):
  x=acoustic_result(envelope(events(),vocal()),'a',True,False)
  self.assertEqual(x['status'],'completed');self.assertEqual(x['voice'],[]);self.assertEqual(x['stages']['vocal']['status'],'not_requested');self.assertEqual(set(x['engines']),{'events'})
  x=acoustic_result(envelope(events(),vocal()),'a',False,True)
  self.assertEqual(x['events'],[]);self.assertEqual(set(x['engines']),{'vocal'})
 def test_vocal_uncertainty_is_explicit_and_warning_text_is_bounded(self):
  v=vocal();v['warnings']=['vocal_presence_uncertain','untrusted provider prose']
  x=acoustic_result(envelope(events(),v),'a',True,True)
  self.assertEqual(x['status'],'completed');self.assertEqual(x['quality']['warnings'],['vocal_presence_uncertain'])
  v['warnings']=None
  self.assertEqual(acoustic_result(envelope(events(),v),'a',True,True)['status'],'completed')
  v['warnings']=['vocal_not_detected']
  self.assertEqual(acoustic_result(envelope(events(),v),'a',True,False)['quality']['warnings'],[])
 def test_voice_only_global_metadata_failure_is_failed_not_unrequested(self):
  value=envelope(None,vocal());value['duration_ms']=-1
  result=acoustic_result(value,'a',False,True)
  self.assertEqual(result['status'],'failed')
  self.assertEqual(result['stages']['vocal']['status'],'failed')
  self.assertEqual(result['stages']['events']['status'],'not_requested')
 def test_voice_availability_rejected_before_upload_and_strict_options(self):
  with TemporaryDirectory() as name, TestClient(create_app(Settings(data_dir=Path(name),token='tier-test',backend='speech',sound_enabled=True,voice_enabled=False))) as c:
   c.headers['Authorization']='Bearer tier-test'
   self.assertFalse(c.get('/v1/capabilities').json()['voice_analysis'])
   r=c.post('/v1/jobs',data={'options':json.dumps({'analyze_voice':True})},files={'files':('a.wav',b'x')});self.assertEqual(r.status_code,422)
   with c.app.state.store.connect() as con:self.assertEqual(con.execute('select count(*) from jobs').fetchone()[0],0)
  with self.assertRaises(ValueError):Options(analyze_voice='true')
 def test_download_choices_are_independent_on_both_speech_routes(self):
  for route in ['cpu','qwen']:
   speech=selection(route=route,sound='none');event=selection(route=route,sound='ast');extended=selection(route=route,sound='ast',voice='4b')
   self.assertEqual(set(event['models'])-set(speech['models']),{'ast-events'})
   self.assertEqual(set(extended['models'])-set(event['models']),{'moss-4b'})
   self.assertNotIn('MOSS_AUDIO_MODEL',event['environment'])
   self.assertFalse(event['experimental']);self.assertTrue(extended['experimental'])
