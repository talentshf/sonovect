import base64,io,json,threading,time,unittest,wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from openai import OpenAI
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.worker import Worker


def audio():
    out=io.BytesIO()
    with wave.open(out,'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*1600)
    return out.getvalue()


class NoSpeech:
    def process(self,*args):raise AssertionError('independent audio must not run ASR')


class AudioAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.settings=Settings(data_dir=Path(self.temp.name),token='audio-test-only',backend='speech',
            sound_url='http://events',understanding_url='http://audio-model/v1',understanding_model='omni-audio',sync_timeout=2)
        self.app=create_app(self.settings);self.client=TestClient(self.app);self.client.headers['Authorization']='Bearer '+self.settings.token
        self.worker=Worker(self.settings,NoSpeech());self.stop=threading.Event()
        def serve():
            while not self.stop.is_set():
                if not self.worker.run_once():self.stop.wait(.01)
        self.thread=threading.Thread(target=serve)
    def tearDown(self):
        self.stop.set()
        if self.thread.ident:self.thread.join(3)
        self.client.close();self.temp.cleanup()

    def test_audio_contracts_are_independent_and_keep_real_class_scores(self):
        classification={'scores':[{'label':'Speech','score':.91},{'label':'Music','score':.1}],
            'engine':{'model':'ast','revision':'pinned'},'aggregation':'duration-weighted-window-mean-sigmoid','window_seconds':10.0}
        def classify(settings,path,top_k):
            with wave.open(str(path)) as wav:self.assertEqual(wav.getframerate(),16000)
            return classification
        def understand(settings,path,question,duration):
            self.assertEqual(question,'What is audible?');self.assertGreater(path.stat().st_size,44)
            return {'text':'A person speaking.','model':'omni-audio','identity_source':'operator-configuration','input':'audio','requires_review':True}
        with patch('sonovect.audio_tasks.classify',side_effect=classify),patch('sonovect.audio_tasks.understand',side_effect=understand):
            self.thread.start()
            result=self.client.post('/models/ast-audioset',content=audio(),headers={'Content-Type':'audio/wav'})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json(),classification['scores'])
            self.assertEqual(result.headers['x-sonovect-aggregation'],classification['aggregation'])
            sdk=OpenAI(base_url='http://testserver/v1',api_key=self.settings.token,http_client=self.client,max_retries=0,_strict_response_validation=True)
            result=sdk.chat.completions.with_raw_response.create(model='omni-audio',modalities=['text'],messages=[{'role':'user','content':[
                {'type':'text','text':'What is audible?'},{'type':'input_audio','input_audio':{'format':'wav','data':base64.b64encode(audio()).decode()}}]}])
            self.assertEqual(result.parse().choices[0].message.content,'A person speaking.')
            job=result.headers['x-sonovect-job-id']
            self.assertEqual(self.worker.store.get(job)['result'],[])
            self.assertEqual(self.client.get(f'/v1/jobs/{job}/result').status_code,409)
            self.assertTrue(self.client.get(f'/v1/jobs/{job}/analysis').json()[0]['understanding']['requires_review'])

    def test_retry_preserves_completed_classification_when_understanding_failed(self):
        classification={'scores':[{'label':'Speech','score':.9}],'engine':{'model':'ast','revision':'pinned'},
            'aggregation':'duration-weighted-window-mean-sigmoid','window_seconds':10.0}
        response=self.client.post('/v1/jobs',files={'files':('voice.wav',audio())},data={'options':json.dumps({
            'transcribe':False,'classify_audio':True,'audio_question':'Describe the sound'})})
        job=response.json()['id']
        with patch('sonovect.audio_tasks.classify',return_value=classification) as classify,patch('sonovect.audio_tasks.understand',side_effect=RuntimeError('failed')) as understand:
            self.worker.run_once()
            self.assertEqual(self.worker.store.public(job)['status'],'partial')
            self.assertEqual(self.worker.store.get(job)['analysis'][0]['stages']['classification']['status'],'completed')
            self.assertTrue(any(x['type']=='stage.failed' and x['data']['stage']=='understanding' for x in self.worker.store.events(job)))
            self.worker.store.retry(job)
            understand.side_effect=None;understand.return_value={'text':'Speech','model':'omni-audio','identity_source':'operator-configuration','input':'audio','requires_review':True}
            self.worker.run_once()
            self.assertEqual(classify.call_count,1);self.assertEqual(understand.call_count,2)
            self.assertEqual(self.worker.store.public(job)['status'],'succeeded')

    def test_invalid_audio_requests_never_enter_queue(self):
        for payload in ({'model':'omni-audio','messages':['invalid']},{'model':'omni-audio','messages':[]},
            {'model':'omni-audio','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com'}}]}]}):
            response=self.client.post('/v1/chat/completions',json=payload)
            self.assertEqual(response.status_code,400,response.text)
        response=self.client.post('/models/ast-audioset',json={'inputs':'invalid','parameters':{'top_k':5}})
        self.assertEqual(response.status_code,400)
        with self.worker.store.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
