import unittest
from sonovect.evaluation import characters, diarization, edit_counts, evaluate, event_detection, words


class AccuracyTests(unittest.TestCase):
    def test_exact_edits_and_uncapped_rate(self):
        self.assertEqual(edit_counts("abc", "adc")["substitutions"], 1)
        self.assertEqual(edit_counts("abc", "ac")["deletions"], 1)
        self.assertEqual(edit_counts("abc", "abxc")["insertions"], 1)
        self.assertEqual(edit_counts("a", "bbbb")["error_rate"], 4)
        self.assertIsNone(edit_counts("", "a")["error_rate"])

    def test_normalization_retains_disfluency_and_lexical_errors(self):
        self.assertEqual(characters("嗯，<sil>３个人。"), "嗯3个人")
        self.assertEqual(words("DON’T re-write!"), ["don't", "re", "write"])

    def test_speaker_labels_are_permutation_invariant(self):
        ref = [{"start_ms": 0, "end_ms": 1000, "speaker": "A"}, {"start_ms": 1000, "end_ms": 2000, "speaker": "B"}]
        hyp = [{"start_ms": 0, "end_ms": 1000, "speaker": "9"}, {"start_ms": 1000, "end_ms": 2000, "speaker": "4"}]
        self.assertEqual(diarization(ref, hyp, 2000)["der"], 0)
        self.assertEqual(diarization(ref, hyp[:1], 2000)["der"], 0.5)

    def test_overlap_and_collar_have_analytical_scores(self):
        ref = [{"start_ms": 0, "end_ms": 1000, "speaker": "A"}, {"start_ms": 500, "end_ms": 1000, "speaker": "B"}]
        hyp = [{"start_ms": 0, "end_ms": 1000, "speaker": "1"}]
        result = diarization(ref, hyp, 1500)
        self.assertAlmostEqual(result["der"], 1 / 3)
        self.assertEqual(result["missed_speaker_ms"], 500)
        self.assertEqual(result["reference_overlap_ms"], 500)
        result = diarization(ref, hyp, 1500, 250)
        self.assertGreater(result["excluded_collar_ms"], 0)

    def test_assignment_maximizes_global_overlap_not_greedy_pair(self):
        ref = [{"start_ms": 0, "end_ms": 1000, "speaker": "a"}, {"start_ms": 1000, "end_ms": 2000, "speaker": "b"}]
        hyp = [{"start_ms": 0, "end_ms": 1600, "speaker": "x"}, {"start_ms": 0, "end_ms": 900, "speaker": "y"}]
        self.assertEqual(diarization(ref, hyp, 2000)["speaker_mapping"], {"x": "b", "y": "a"})

    def test_failed_case_remains_in_error_denominator(self):
        dataset = {"cases": [{"id": "one", "text": "abc"}, {"id": "two", "text": "abc"}]}
        predictions = {"cases": [{"id": "one", "status": "succeeded", "transcript": {"text": "abc"}}, {"id": "two", "status": "failed"}]}
        result = evaluate(dataset, predictions)
        self.assertEqual(result["groups"]["default"]["cer"]["error_rate"], 0.5)
        with self.assertRaises(ValueError):
            evaluate(dataset, {"cases": predictions["cases"][:1]})

    def test_event_aliases_do_not_confuse_train_with_rain(self):
        self.assertFalse(event_detection(["rain"], [{"label": "train passing"}])["target_detected"])
        self.assertTrue(event_detection(["rain", "雨声"], [{"label": "雨声持续"}])["target_detected"])


if __name__ == "__main__":
    unittest.main()
