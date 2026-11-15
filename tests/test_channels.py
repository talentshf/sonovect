import array,io,json,unittest,wave
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.recognition import Recognition
from sonovect.worker import Worker

class Engine:
    def __init__(self):self.samples=[]
    def process(self,path,key,options):
        with wave.open(str(path)) as audio:
            samples=array.array('h',audio.readframes(audio.getnframes()))
            self.samples.append(sum(samples)/len(samples))
        return Recognition({'key':key,'text':str(len(self.samples))},{'key':key,'status':'not_requested'},{})

class ChannelTests(unittest.TestCase):
    def test_two_channels_are_not_mixed_and_source_clock_is_preserved(self):
        with TemporaryDirectory() as folder:
            settings=Settings(data_dir=Path(folder),token='channel-test-only',backend='speech')
            app=create_app(settings);engine=Engine();worker=Worker(settings,engine)
            data=io.BytesIO()
            with wave.open(data,'wb') as audio:
                audio.setparams((2,2,16000,0,'NONE','not compressed'))
                audio.writeframes(array.array('h',[1000,-2000]*1600).tobytes())
            with TestClient(app) as client:
                client.headers['Authorization']='Bearer '+settings.token
                response=client.post('/v1/jobs',files={'files':('stereo.wav',data.getvalue())},data={'options':json.dumps({'channel_mode':'independent'})})
                job=response.json()['id'];worker.run_once()
                value=worker.store.get(job)
                self.assertEqual(value['state'],'succeeded')
                self.assertEqual([s['channel'] for s in value['sources']],[0,1])
                self.assertEqual(engine.samples,[1000.0,-2000.0])
                self.assertEqual([s['media']['duration_ms'] for s in value['sources']],[100,100])
                self.assertEqual([s['media']['source_channel'] for s in value['sources']],[0,1])
                self.assertEqual(len(client.get(f'/v1/jobs/{job}/result').json()),2)
