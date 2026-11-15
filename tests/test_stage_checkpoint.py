import json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.recognition import Recognition
from sonovect.worker import Worker
from test_audio_api import audio

class Backend:
    def __init__(self):self.calls=[]
    def process_stream(self,path,key,options,progress):
        self.calls.append(options)
        if options['transcribe']:
            progress({'stage':'speech.completed','result':{'key':key,'text':'保存的原文'},'evidence':{'language':'Chinese'}})
            raise KeyboardInterrupt()
        return Recognition(None,{'key':key,'status':'completed','stages':{'vocal':{'status':'completed'}}},{})

class StageCheckpointTests(unittest.TestCase):
    def test_worker_interruption_in_auxiliary_stage_does_not_repeat_asr(self):
        with TemporaryDirectory() as folder:
            settings=Settings(data_dir=Path(folder),token='checkpoint-test-only',backend='speech',voice_enabled=True)
            backend=Backend();worker=Worker(settings,backend)
            with TestClient(create_app(settings)) as client:
                client.headers['Authorization']='Bearer '+settings.token
                response=client.post('/v1/jobs',files={'files':('voice.wav',audio())},data={'options':json.dumps({'analyze_voice':True})})
                job=response.json()['id']
                with self.assertRaises(KeyboardInterrupt):worker.run_once()
                self.assertEqual(worker.store.get(job)['result'][0]['text'],'保存的原文')
                with worker.store.connect() as con:con.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(job,))
                worker.run_once()
                self.assertEqual([x['transcribe'] for x in backend.calls],[True,False])
                self.assertEqual(worker.store.public(job)['status'],'succeeded')
                self.assertEqual(len(worker.store.get(job)['result']),1)
