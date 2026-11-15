import json,threading,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sonovect.config import Settings
from sonovect.api import create_app
from sonovect.listen import install,parameters
from sonovect.recognition import Recognition
from sonovect.worker import Worker
from test_audio_api import audio

class Engine:
    def __init__(self):self.calls=0
    def process(self,path,key,options):
        self.calls+=1
        return Recognition({'key':key,'text':'你好'},{'key':key,'status':'not_requested'},
            {'transcripts':[{'sentences':[{'words':[{'text':'你好','begin_time':0,'end_time':100}]}]}]})

class ListenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.settings=Settings(data_dir=Path(self.tmp.name),token='listen-test-only',backend='speech',realtime_enabled=True,sync_timeout=2)
        self.engine=Engine();self.app=FastAPI()
        install(self.app,self.settings,None,None,self.engine)
        self.client=TestClient(self.app);self.headers={'Authorization':'Token '+self.settings.token}
    def tearDown(self):self.client.close();self.tmp.cleanup()

    def test_deepgram_finalization_is_real_and_returns_word_evidence(self):
        with self.client.websocket_connect('/v1/listen?encoding=linear16&sample_rate=16000&endpointing=false&interim_results=false',headers=self.headers) as ws:
            ws.send_bytes(b'\0\0'*1600)
            self.assertEqual(self.engine.calls,0)
            ws.send_text('{"type":"Finalize"}')
            value=ws.receive_json();self.assertEqual(value['type'],'Results');self.assertTrue(value['is_final'])
            self.assertEqual(value['channel']['alternatives'][0]['transcript'],'你好')
            self.assertNotIn('confidence',value['channel']['alternatives'][0])
            ws.send_bytes(b'\0\0'*1600);ws.send_text('{"type":"CloseStream"}')
            second=ws.receive_json();self.assertEqual(second['channel']['alternatives'][0]['words'][0]['start'],.1)
            self.assertEqual(ws.receive_json()['type'],'Metadata')
        self.assertEqual(self.engine.calls,2)

    def test_funasr_offline_does_not_invent_two_pass_outputs(self):
        with self.client.websocket_connect('/v1/funasr',headers=self.headers) as ws:
            ws.send_json({'mode':'offline','wav_name':'test','wav_format':'pcm','audio_fs':16000,'is_speaking':True})
            ws.send_bytes(b'\0\0'*1600);ws.send_json({'is_speaking':False})
            value=ws.receive_json();self.assertEqual(value,{'mode':'offline','wav_name':'test','text':'你好','is_final':False})
        with self.client.websocket_connect('/v1/funasr',headers=self.headers) as ws:
            ws.send_json({'mode':'2pass'});self.assertIn('error',ws.receive_json())
        self.assertEqual(self.engine.calls,1)

    def test_native_token_authorization_and_file_contract(self):
        app=create_app(self.settings);worker=Worker(self.settings,self.engine);stop=threading.Event()
        def serve():
            while not stop.is_set():
                if not worker.run_once():stop.wait(.01)
        thread=threading.Thread(target=serve);thread.start()
        try:
            with TestClient(app) as client:
                self.assertEqual(client.post('/v1/listen',content=audio()).status_code,401)
                result=client.post('/v1/listen',content=audio(),headers=self.headers)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['results']['channels'][0]['alternatives'][0]['words'][0]['word'],'你好')
        finally:stop.set();thread.join(3)
