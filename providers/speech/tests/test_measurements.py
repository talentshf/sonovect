import math
import unittest
from unittest.mock import patch
import numpy as np
from sonovect.voice_measurements import MeasurementDetector, measurements


class MeasurementSignalTests(unittest.TestCase):
    def test_known_frequency_and_pcm_amplitude_without_any_model(self):
        import importlib.util
        if importlib.util.find_spec('librosa') is None:
            self.skipTest('Numeric dependency runs in the dedicated Linux image')
        x=(.2*np.sin(2*np.pi*220*np.arange(32000)/16000)).astype(np.float32)
        rows=measurements(x,0,2000)
        self.assertAlmostEqual(rows[1]['value'],20*math.log10(.2/math.sqrt(2)),places=5)
        self.assertLess(abs(rows[0]['value']-220),3)

    def test_no_speech_and_invalid_context_never_calculate(self):
        detector=MeasurementDetector()
        with patch('sonovect.voice_measurements.measurements',side_effect=AssertionError('must skip')):
            out=detector.analyze(np.zeros(16000,dtype=np.float32),{'speech_regions':[]})
            self.assertEqual(out['measurements'],[]);self.assertEqual(detector.windows,0)
            with self.assertRaises(ValueError):detector.analyze(np.zeros(16000),{})

    def test_only_real_intersecting_windows_have_numbers(self):
        detector=MeasurementDetector(window_seconds=1)
        with patch('sonovect.voice_measurements.measurements',return_value=[]) as run:
            detector.analyze(np.zeros(48000),{'speech_regions':[[1100,1900]]})
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[1:],(1000,2000))

    def test_short_silence_has_no_invented_pitch_or_infinity(self):
        import importlib.util
        if importlib.util.find_spec('librosa') is None:self.skipTest('Numeric dependency runs in dedicated Linux image')
        out=measurements(np.zeros(20,dtype=np.float32),0,1)
        self.assertEqual([x['status'] for x in out],['unavailable','unavailable'])
        self.assertEqual([x['value'] for x in out],[None,None])
