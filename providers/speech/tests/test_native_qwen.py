import importlib.util
from pathlib import Path
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

path = Path(__file__).resolve().parents[1] / "qwen-worker/native_runtime.py"
spec = importlib.util.spec_from_file_location("native_qwen", path)
runtime = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


class NativeQwenAlignmentTests(unittest.TestCase):
    def test_preserves_model_classes_including_zero_duration_and_reverse_order(self):
        result = runtime.alignment_items([2, 2, 1, 3], ["one", "two"])
        self.assertEqual([(w.start_time, w.end_time) for w in result.items], [(0.16, 0.16), (0.08, 0.24)])
        # The public boundary validates/rejects these spans; this decoder never repairs them.

    def test_missing_class_does_not_make_up_an_alignment(self):
        self.assertIsNone(runtime.alignment_items([1], ["word"]))


class ContextEchoTests(unittest.TestCase):
    terms = "紫云科技, 长风模块, 远海工坊"
    context = "Vocabulary: " + terms

    def test_complete_and_partial_vocabulary_echo_with_punctuation(self):
        for text in ["紫云科技，长风模块，远海工坊。", "嗯，紫云科技，长风模块。然后继续。",
                     "长风模块、远海工坊。"]:
            with self.subTest(text=text):
                self.assertTrue(runtime.context_echo_suspected(text, self.context))

    def test_genuine_individual_and_separate_term_mentions_are_not_echoes(self):
        for text in ["紫云科技。", "我在紫云科技工作，今天来讨论长风模块的设计。", "大家好。", ""]:
            with self.subTest(text=text):
                self.assertFalse(runtime.context_echo_suspected(text, self.context))

    def test_unlabelled_request_and_configured_prose_are_covered(self):
        self.assertTrue(runtime.context_echo_suspected("紫云科技，长风模块，远海工坊。", self.terms))
        context = "上一段转写仅用于语境连续，不代表本段音频的内容。"
        self.assertTrue(runtime.context_echo_suspected(context, context))

    def test_empty_context_and_duplicate_terms_do_not_trigger(self):
        self.assertFalse(runtime.context_echo_suspected(self.terms, ""))
        self.assertFalse(runtime.context_echo_suspected("紫云科技", "Vocabulary: 紫云科技, 紫云科技"))

    def test_unicode_case_and_vocabulary_labels_are_normalized(self):
        self.assertTrue(runtime.context_echo_suspected(
            "ＱＷＥＮ、ＳＯＮＯＶＥＣＴ。", "Technical terms: Qwen, Sonovect"))
        self.assertTrue(runtime.context_echo_suspected("紫云科技、长风模块。", "术语：紫云科技、长风模块"))


class NativeQwenContextRecheckTests(unittest.TestCase):
    def setUp(self):
        self.torch = patch.dict(sys.modules, {"torch": SimpleNamespace(inference_mode=nullcontext)})
        self.torch.start()
        self.addCleanup(self.torch.stop)
        self.model = runtime.NativeQwenASR()
        self.model._decode = Mock()
        self.model._align = Mock(return_value=object())
        self.wave_a, self.wave_b = [0.1, 0.2], [0.3, 0.4]
        self.context = "Vocabulary: 紫云科技, 长风模块, 远海工坊"
        self.echo = {"transcription": "紫云科技，长风模块，远海工坊。", "language": "Chinese"}

    def test_only_suspect_chunk_is_redecoded_and_final_text_is_aligned(self):
        second = {"transcription": "正常的第二段。", "language": "Chinese"}
        self.model._decode.side_effect = [[self.echo, second], [{"transcription": "我们继续讨论。", "language": "Chinese"}]]
        results = self.model.transcribe(audio=[(self.wave_a, 16000), (self.wave_b, 16000)],
            context=[self.context, self.context], language=["Chinese", "Chinese"])
        self.assertEqual([r.text for r in results], ["我们继续讨论。", "正常的第二段。"])
        self.assertEqual([r.context_echo_rechecked for r in results], [True, False])
        self.assertEqual(self.model._decode.call_args_list[1].args, ([self.wave_a], ["Chinese"], [""]))
        self.assertEqual([call.args[1] for call in self.model._align.call_args_list], ["我们继续讨论。", "正常的第二段。"])
        self.assertEqual(self.model._decode.call_count, 2)

    def test_genuinely_spoken_term_list_is_preserved_after_one_recheck(self):
        self.model._decode.side_effect = [[self.echo], [self.echo]]
        result = self.model.transcribe(audio=[(self.wave_a, 16000)], context=self.context)[0]
        self.assertEqual(result.text, self.echo["transcription"])
        self.assertTrue(result.context_echo_rechecked)
        self.assertEqual(self.model._decode.call_count, 2)
        self.model._align.assert_called_once_with(self.wave_a, result.text, "Chinese")

    def test_empty_acoustic_recheck_stays_empty_without_made_up_alignment(self):
        self.model._decode.side_effect = [[self.echo], [{"transcription": "", "language": ""}]]
        result = self.model.transcribe(audio=[(self.wave_a, 16000)], context=self.context)[0]
        self.assertEqual(result.text, "")
        self.assertIsNone(result.time_stamps)
        self.model._align.assert_not_called()

    def test_unhinted_output_is_not_retried_and_individual_terms_are_retained(self):
        for text, context in [(self.echo["transcription"], ""), ("今天讨论紫云科技。", self.context)]:
            with self.subTest(context=context):
                self.model._decode.reset_mock()
                self.model._decode.return_value = [{"transcription": text, "language": "Chinese"}]
                result = self.model.transcribe(audio=[(self.wave_a, 16000)], context=context, return_time_stamps=False)[0]
                self.assertEqual(result.text, text)
                self.assertFalse(result.context_echo_rechecked)
                self.assertIsNone(result.time_stamps)
                self.model._decode.assert_called_once()

    def test_recheck_failure_never_returns_known_suspect_result_as_success(self):
        self.model._decode.side_effect = [[self.echo], RuntimeError("inference_failed")]
        with self.assertRaisesRegex(RuntimeError, "inference_failed"):
            self.model.transcribe(audio=[(self.wave_a, 16000)], context=self.context)
        self.model._align.assert_not_called()

    def test_batch_context_count_mismatch_is_rejected_before_inference(self):
        with self.assertRaisesRegex(ValueError, "audio_language_context_count_mismatch"):
            self.model.transcribe(audio=[(self.wave_a, 16000), (self.wave_b, 16000)], context=[self.context])
        self.model._decode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
