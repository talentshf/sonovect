import copy
import json
from pathlib import Path
import unittest
import jsonschema
from pydantic import ValidationError
from sonovect.models import Options, transcript_json
from sonovect.results import acoustic_result, as_srt, native_result, speech_result


class ResultContractTests(unittest.TestCase):
    def test_native_speech_fields_are_lossless_and_extras_are_separate(self):
        source = {"key": "/private/input.wav", "text": "你好。Hello!",
                  "timestamp": [[120, 420], [450, 900]],
                  "sentence_info": [{"start": 120, "end": 900, "text": "你好。Hello!",
                                     "timestamp": [[120, 420], [450, 900]], "spk": 7}],
                  "spk_embedding": [[0.3]], "environment": "rain"}
        before = copy.deepcopy(source)
        result = native_result(source, "audio_0000", True)
        self.assertEqual(result, {k: v for k, v in source.items() if k in {"text", "timestamp", "sentence_info"}} | {"key": "audio_0000"})
        self.assertEqual(before, source)
        self.assertNotIn("spk", native_result(source, "audio_0000", False)["sentence_info"][0])
        schema = json.loads((Path(__file__).parents[1] / "contracts/funasr-result.schema.json").read_text())
        jsonschema.validate([result], schema)

    def test_missing_timing_and_speakers_are_not_invented(self):
        self.assertEqual(native_result({"text": "unaligned"}, "a", True), {"key": "a", "text": "unaligned"})
        self.assertEqual(native_result({"text": "", "timestamp": [], "sentence_info": []}, "a", True),
                         {"key": "a", "text": "", "timestamp": [], "sentence_info": []})

    def test_milliseconds_do_not_accept_seconds_strings_booleans_or_reverse_spans(self):
        for span in ([1.2, 2.5], [True, 2], ["1", "2"], [20, 10], [-1, 10]):
            with self.subTest(span=span), self.assertRaises(ValidationError):
                transcript_json({"key": "a", "text": "test", "timestamp": [span]})

    def test_adapter_preserves_text_and_actual_alignment_and_local_speakers(self):
        source = {"text": "你好。Hello!", "segments": [
            {"text": "你好。", "start_ms": 100, "end_ms": 500, "speaker": "SPK_9",
             "words": [{"text": "你好", "start_ms": 100, "end_ms": 450}], "events": ["rain"]},
            {"text": "Hello!", "start_ms": 800, "end_ms": 1400, "speaker": "SPK_2"}],
            "words": [{"text": "你好", "start_ms": 100, "end_ms": 450}]}
        value = speech_result(source, "a", True)
        self.assertEqual(value["text"], source["text"])
        self.assertEqual([s["spk"] for s in value["sentence_info"]], [0, 1])
        self.assertNotIn("timestamp", value["sentence_info"][1])
        self.assertNotIn("events", value["sentence_info"][0])
        self.assertEqual(value["timestamp"], [[100, 450]])
        self.assertEqual(speech_result(source, "b", True)["sentence_info"][0]["spk"], 0)

    def test_acoustic_windows_are_independent_and_not_exact_event_spans(self):
        value = {"duration_ms":5000,"stage_payloads":{
            "events":{"payload":{"parse_valid":True,"events_valid":True,"engine":{"model":"ast","revision":"fixed"},
                "events":[{"label":"Traffic","kind":"environment-state","start_ms":0,"end_ms":5000,"temporal_resolution":"analysis-window"},{"label":"Speech"}]}},
            "vocal":{"payload":{"parse_valid":True,"vocal_valid":True,"engine":{"model":"vocal","revision":"fixed"},"emotions":[{"label":"calm"}]}}}}
        output = acoustic_result(value, "a", True, True)
        self.assertEqual(len(output["events"]), 1)
        self.assertEqual(output["events"][0]["temporal_resolution"], "analysis-window")
        self.assertNotIn("start_ms", output["emotions"][0])
        self.assertEqual(output["quality"]["duration_ms"], 5000)
        self.assertEqual(acoustic_result(value, "a", False)["events"], [])

    def test_srt_uses_existing_timing_and_rejects_multiple_clocks(self):
        value = [{"key": "a", "text": "Hello", "sentence_info": [{"start": 1230, "end": 2480, "text": "Hello"}]}]
        self.assertEqual(as_srt(value), "1\n00:00:01,230 --> 00:00:02,480\nHello\n")
        with self.assertRaises(ValueError):
            as_srt(value * 2)

    def test_acoustic_completion_requires_evidence_and_invalid_items_fail_safely(self):
        for source in ({}, {"enrichment": {"lanes": {"speech": {"state": "completed"}}}},
                       {"enrichment": {"lanes": {"acoustic": {"state": "completed"}}}},
                       {"enrichment": {"lanes": {"acoustic": {"state": "completed"}},
                        "acoustic_analysis": {"events": [{"label": "rain", "start_ms": -1, "end_ms": 100}]}}}):
            with self.subTest(source=source):
                value = acoustic_result(source, "a", True)
                self.assertEqual(value["status"], "failed")
                self.assertEqual(value["events"], [])
        self.assertEqual(acoustic_result({"stage_payloads":{"events":{"payload":{"parse_valid":True,"events_valid":True,"events":[],"engine":{"model":"ast","revision":"fixed"}}}}}, "a", True)["status"], "completed")

    def test_unrequested_analysis_does_not_fail_on_bad_optional_quality(self):
        output = acoustic_result({"duration_ms": "invalid"}, "a", False)
        self.assertEqual(output["status"], "not_requested")
        self.assertNotIn("error", output)
        self.assertIn("provider_analysis_invalid", output["quality"]["warnings"])

    def test_options_reject_unknown_business_fields_and_coercion(self):
        for value in ({"owner": "someone"}, {"speakers": "true"}, {"hotwords": [""]}):
            with self.assertRaises(ValidationError):
                Options.model_validate(value)


if __name__ == "__main__":
    unittest.main()
