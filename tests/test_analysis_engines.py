import unittest
from sonovect.results import acoustic_result, native_result


class AnalysisEngineTests(unittest.TestCase):
    def payload(self):
        return {'stage_payloads': {
            'events': {'payload': {'parse_valid':True,'events_valid':True,
                'engine':{'model':'event-model','revision':'fixed-events'},
                'events':[{'label':'Rain','confidence':0.7,'start_ms':0,'end_ms':5000}]}},
            'vocal': {'payload': {'parse_valid':True,'vocal_valid':True,
                'engine':{'model':'vocal-model','revision':'fixed-vocal'},'emotions':[{'label':'calm'}]}}}}


    def test_independent_engine_provenance_never_changes_native_speech(self):
        value = self.payload()
        output = acoustic_result(value, 'clip', True, True)
        self.assertEqual(output['engines']['events']['model'], 'event-model')
        self.assertEqual(output['engines']['vocal']['model'], 'vocal-model')
        self.assertEqual(output['events'][0]['confidence'], 0.7)
        speech = {'text': '原生文本', 'timestamp': [[0, 100]], 'sentence_info': [{'text': '原生文本', 'start': 0, 'end': 100}]}
        self.assertEqual(native_result(speech, 'clip', False), {**speech, 'key': 'clip'})
        self.assertNotIn('engines', acoustic_result(value, 'clip', False))

    def test_invalid_provenance_fails_analysis_boundary(self):
        value = self.payload();value['stage_payloads']['events']['payload']['engine']['revision'] = ''
        output = acoustic_result(value, 'clip', True)
        self.assertEqual(output['status'], 'failed')
        self.assertEqual(output['error'], 'sound_analysis_failed')
