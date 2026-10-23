import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('event_detector', Path(__file__).parents[1] / 'event-worker/event_detector.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EventDetectorTests(unittest.TestCase):
    def test_speech_identity_silence_filter_threshold_and_window(self):
        labels = {0: 'Speech', 1: 'Male speech, man speaking', 2: 'Rain', 3: 'Silence', 4: 'Sneeze'}
        result = module.select_events([0.99, 0.9, 0.7, 0.95, 0.09], labels, 10000, 12345, 0.1, 3)
        self.assertEqual([x['label'] for x in result], ['Rain'])
        self.assertEqual((result[0]['start_ms'], result[0]['end_ms']), (10000, 12345))
        self.assertEqual(result[0]['temporal_resolution'], 'analysis-window')
        self.assertAlmostEqual(result[0]['confidence'], 0.7)

    def test_multilabel_does_not_softmax_and_top_k_is_bounded(self):
        result = module.select_events([0.8, 0.7, 0.6], {0: 'Rain', 1: 'Thunder', 2: 'Wind'}, 0, 5000, 0.1, 2)
        self.assertEqual([x['label'] for x in result], ['Rain', 'Thunder'])
        self.assertEqual(sum(x['confidence'] for x in result), 1.5)

    def test_invalid_memory_and_context_controls_rejected(self):
        for values in ({'threshold': float('nan')}, {'top_k': 0}, {'top_k': 11},
                       {'window_seconds': 90}, {'window_seconds': 0}, {'window_seconds': 1e-6}, {'threads': 33}):
            with self.assertRaises(ValueError):
                module.EventDetector(**values)

    def test_empty_control_never_loads_a_model(self):
        class Empty:
            def __len__(self):return 0
        detector = module.EventDetector()
        detector._load = lambda: self.fail('Silence must not load weights')
        self.assertEqual(detector.detect(Empty()), [])

    def test_short_tail_pads_features_without_extending_media_time(self):
        import numpy as np
        audio = np.ones(160000 + 160, dtype=np.float32)
        windows = list(module.analysis_windows(audio, 16000, 10))
        self.assertEqual([len(chunk) for chunk, _, _ in windows], [160000, 400])
        self.assertEqual([(start, end) for _, start, end in windows], [(0, 10000), (10000, 10010)])
        self.assertTrue(np.array_equal(windows[-1][0][:160], audio[-160:]))
        self.assertTrue(np.all(windows[-1][0][160:] == 0))

    def test_submillisecond_tail_cannot_create_zero_duration_event(self):
        import numpy as np
        windows = list(module.analysis_windows(np.ones(160004, dtype=np.float32), 16000, 10))
        self.assertEqual([(start, end) for _, start, end in windows], [(0, 10000)])

    def test_unrepresentably_short_audio_never_loads_weights(self):
        import numpy as np
        detector = module.EventDetector()
        detector._load = lambda: self.fail('No millisecond observation can be made')
        self.assertEqual(detector.detect(np.ones(4, dtype=np.float32)), [])
