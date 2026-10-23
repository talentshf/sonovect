import ast,asyncio,unittest
from pathlib import Path
from typing import Any,Optional
from unittest.mock import AsyncMock
from fastapi import HTTPException

ROOT=Path(__file__).parents[1]
class AcousticRouteTests(unittest.TestCase):
 def pipeline(self,fail_events=False,fail_measurements=False,fail_voice=False):
  source=(ROOT/'api/app.py').read_text();tree=ast.parse(source)
  functions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'_pipeline_once','_payloads','_strict_stage_payloads'}]
  calls=[]
  async def post(url,path,parts,data,timeout):
   calls.append((url,path,data))
   if (url=='events' and fail_events) or (url=='measurements' and fail_measurements) or (url=='moss' and fail_voice):raise RuntimeError('offline')
   return {'duration_ms':1000,'speech_regions':[],'events_valid':True,'vocal_valid':True,'measurements_valid':True,'parse_valid':True}
  control=AsyncMock(return_value={'status':'unloaded','manager':{'resident':False,'busy':False}})
  ns={'Any':Any,'Optional':Optional,'AudioPart':object,'HTTPException':HTTPException,'asyncio':asyncio,'json':__import__('json'),'SOUND_ENABLED':True,'VOICE_ENABLED':True,'VOICE_BACKEND':'moss','MEASUREMENTS_ENABLED':True,'MEASUREMENTS_URL':'measurements','SEGMENTATION_URL':'seg','QWEN_URL':'asr','MOSS_URL':'moss','EVENTS_URL':'events','_post_audio':post,'_post_control':control,'_release_sound_before_speech':AsyncMock(),'_safe_error':lambda x:'stage_failed','build_request_plan':lambda *a,**k:{},'_compose':lambda *a,**k:k}
  ns.update({k:1 for k in ['SEGMENTATION_TIMEOUT','QWEN_TIMEOUT','MOSS_TIMEOUT','EVENTS_TIMEOUT','MEASUREMENTS_TIMEOUT','SEGMENT_TARGET_MS','SEGMENT_HARD_MAX_MS','SEGMENT_MERGE_GAP_MS','SEGMENT_BOUNDARY_SILENCE_MS','SEGMENT_PADDING_MS']})
  exec(compile(ast.Module(body=functions,type_ignores=[]),'<actual-pipeline>','exec'),ns)
  return ns,calls,control
 def test_tiers_only_call_requested_models_and_ast_does_not_unload_asr(self):
  for e,v,expected in [(False,False,['seg','asr']),(True,False,['seg','asr','events']),(True,True,['seg','asr','events','moss']),(False,True,['seg','asr','moss'])]:
   ns,calls,control=self.pipeline();asyncio.run(ns['_pipeline_once']([object()],'en',True,e,False,'proper-name',v))
   self.assertEqual([x[0] for x in calls],expected)
   self.assertEqual(calls[1][2]['context'],'proper-name');self.assertEqual(control.await_count,int(v))
 def test_event_failure_still_runs_requested_vocal_stage(self):
  ns,calls,_=self.pipeline(True);x=asyncio.run(ns['_pipeline_once']([object()],'en',True,True,voice=True))
  self.assertEqual([c[0] for c in calls],['seg','asr','events','moss']);self.assertEqual(x['events_error'],'stage_failed');self.assertIsNone(x['acoustic_error'])
 def test_cpu_vocal_reuses_segmentation_and_does_not_unload_gpu(self):
  ns,calls,control=self.pipeline();ns['VOICE_BACKEND']='emotion2vec'
  asyncio.run(ns['_pipeline_once']([object()],'zh',True,True,voice=True,measure_voice=True))
  control.assert_not_awaited()
  self.assertEqual(__import__('json').loads(calls[-1][2]['speech_context']),[{'speech_regions':[]}])
  self.assertNotIn('measure',calls[-1][2])
  self.assertEqual([c[0] for c in calls],['seg','asr','events','measurements','moss'])
 def test_measurements_work_without_emotion_and_fail_independently(self):
  ns,calls,control=self.pipeline();ns['VOICE_ENABLED']=False
  result=asyncio.run(ns['_pipeline_once']([object()],'en',True,False,measure_voice=True))
  self.assertEqual([c[0] for c in calls],['seg','asr','measurements']);control.assert_not_awaited()
  self.assertIsNotNone(result['measurement_data'])
  for failed in ['measurements','voice']:
   ns,calls,_=self.pipeline(fail_measurements=failed=='measurements',fail_voice=failed=='voice')
   result=asyncio.run(ns['_pipeline_once']([object()],'en',True,False,voice=True,measure_voice=True))
   self.assertEqual([c[0] for c in calls],['seg','asr','measurements','moss'])
   self.assertEqual(result['measurement_error'],'stage_failed' if failed=='measurements' else None)
   self.assertEqual(result['acoustic_error'],'stage_failed' if failed=='voice' else None)
 def test_moss_parser_requires_vocal_evidence_and_omits_old_event_work(self):
  source=(ROOT/'moss-worker/app.py').read_text();n=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_normalize')
  import importlib.util
  spec=importlib.util.spec_from_file_location('vocal_output',ROOT/'moss-worker/vocal_output.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
  ns={'Any':Any,'EMOTIONS':{'NEUTRAL'},'DEBUG_RAW':False,'audible_description':policy.audible_description};exec(compile(ast.Module(body=[n],type_ignores=[]),'<actual-normalizer>','exec'),ns)
  x=ns['_normalize']({'vocal_present':True,'emotions':[{'label':'NEUTRAL'}],'voice':{'pitch':'low'},'events':[{'label':'Rain'}]},1000,'',-20)
  self.assertTrue(x['vocal_valid']);self.assertEqual(x['voice']['pitch'],'low');self.assertNotIn('events',x)
  self.assertFalse(ns['_normalize']({'unexpected':[]},1000,'',-20)['vocal_valid'])
  x=ns['_normalize']({'vocal_present':True,'emotions':[{'label':'NEUTRAL'}],'voice':{'pitch':'Mid-to-high for a male','texture':'Breathy','speed':['fast']}},1000,'',-20)
  self.assertEqual(x['voice'],{'texture':'Breathy'})

 def test_vocal_presence_is_required_and_negative_or_uncertain_output_is_suppressed(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('vocal_output',ROOT/'moss-worker/vocal_output.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
  source=(ROOT/'moss-worker/app.py').read_text();n=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_normalize')
  ns={'Any':Any,'EMOTIONS':{'NEUTRAL'},'DEBUG_RAW':False,'audible_description':policy.audible_description};exec(compile(ast.Module(body=[n],type_ignores=[]),'<actual-normalizer>','exec'),ns)
  for presence in [False,None,'true',1]:
   value=ns['_normalize']({'vocal_present':presence,'emotions':[{'label':'NEUTRAL'}],'voice':{'pitch':'high'}},1000,'',-20)
   self.assertEqual(value['emotions'],[]);self.assertEqual(value['voice'],{});self.assertFalse(value['vocal_valid'])
  for presence,warning in [(False,'vocal_not_detected'),(None,'vocal_presence_uncertain')]:
   value=ns['_normalize']({'vocal_present':presence,'emotions':[],'voice':{}},1000,'',-20)
   self.assertTrue(value['vocal_valid']);self.assertEqual(value['warnings'],[warning])
  self.assertFalse(ns['_normalize']({'emotions':[],'voice':{}},1000,'',-20)['vocal_valid'])
  self.assertFalse(ns['_normalize']({'vocal_present':True,'emotions':[{'label':{}}],'voice':{}},1000,'',-20)['vocal_valid'])
  self.assertFalse(ns['_normalize']({'vocal_present':True,'emotions':[{'label':'NEUTRAL'},{'label':'NEUTRAL'}],'voice':{}},1000,'',-20)['vocal_valid'])
