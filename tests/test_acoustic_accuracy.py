import unittest
from sonovect.evaluation import binomial_interval, emotion_scores, multilabel_scores


class AcousticAccuracyTests(unittest.TestCase):
    def test_multilabel_false_alarms_use_exhaustive_declared_scope(self):
        result = multilabel_scores([['dog'],[],['rain'],[]],
                                   [['dog','animal'],['dog'],[],[]], ['dog','rain'])
        self.assertEqual(result['micro'], {'tp':1,'fp':1,'fn':1,'tn':5,
                         'precision':0.5,'recall':0.5,'f1':0.5})
        self.assertEqual(result['negative_clip_false_positive_rate']['rate'],0.5)
        self.assertEqual(result['unscored_prediction_counts'],{'animal':1})
        self.assertEqual(result['exact_set_match']['rate'],0.5)

    def test_no_predictions_or_negatives_does_not_invent_precision(self):
        result = multilabel_scores([['dog']], [[]], ['dog'])
        self.assertIsNone(result['micro']['precision'])
        self.assertIsNone(result['negative_clip_false_positive_rate']['rate'])
        self.assertEqual(result['micro']['recall'],0)
        with self.assertRaises(ValueError):multilabel_scores([['unknown']], [[]], ['dog'])

    def test_emotion_abstention_multiple_and_outside_labels_remain_errors(self):
        result = emotion_scores(['HAPPY']*4,
                                [['HAPPY'],[],['HAPPY','SAD'],['SURPRISED']], ['HAPPY','SAD'])
        self.assertEqual(result['strict_accuracy']['rate'],0.25)
        self.assertEqual(result['confusion']['HAPPY'],
                         {'HAPPY':1,'SAD':0,'ABSTAIN':1,'MULTIPLE':1,'OUT_OF_VOCABULARY':1})

    def test_zero_observed_false_alarms_still_have_uncertainty(self):
        interval = binomial_interval(0,80)
        self.assertEqual(interval['rate'],0)
        self.assertGreater(interval['wilson_95'][1],0.04)
