from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


segmentation = _load("speech_segmentation", "api/segmentation.py")
timestamps = _load("speech_timestamp_utils", "qwen-worker/timestamp_utils.py")
text_utils = _load("speech_text_utils", "qwen-worker/text_utils.py")
speaker_policy = _load(
    "speech_speaker_policy",
    "segmentation-worker/speaker_policy.py",
)


class SpeakerContinuityPlanTests(unittest.TestCase):
    def test_same_speaker_micro_regions_are_merged(self) -> None:
        payload = {
            "duration_ms": 26_000,
            "speaker_turns": [
                {"start_ms": 1_000, "end_ms": 6_000, "speaker": "SPK_0"},
                {"start_ms": 6_400, "end_ms": 12_000, "speaker": "SPK_0"},
                {"start_ms": 12_500, "end_ms": 25_000, "speaker": "SPK_0"},
            ],
        }
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual(len(plan["files"][0]), 1)
        self.assertEqual((plan["files"][0][0]["start_ms"], plan["files"][0][0]["end_ms"]), (1_000, 25_000))
        self.assertEqual(plan["files"][0][0]["language"], "auto")

    def test_speaker_change_is_boundary(self) -> None:
        payload = {
            "duration_ms": 12_000,
            "speaker_turns": [
                {"start_ms": 500, "end_ms": 5_000, "speaker": "SPK_0"},
                {"start_ms": 5_100, "end_ms": 10_000, "speaker": "SPK_1"},
            ],
        }
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual([chunk["speaker"] for chunk in plan["files"][0]], ["SPK_0", "SPK_1"])

    def test_soft_target_waits_for_real_pause(self) -> None:
        payload = {
            "duration_ms": 70_000,
            "speaker_turns": [
                {"start_ms": 0, "end_ms": 20_000, "speaker": "SPK_0"},
                {"start_ms": 20_200, "end_ms": 40_000, "speaker": "SPK_0"},
                {"start_ms": 41_000, "end_ms": 60_000, "speaker": "SPK_0"},
            ],
        }
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual([(item["start_ms"], item["end_ms"]) for item in plan["files"][0]], [(0, 40_000), (41_000, 60_000)])

    def test_explicit_language_wins_and_auto_remains_auto(self) -> None:
        payload = {"duration_ms": 5_000, "speech_regions": [{"start_ms": 0, "end_ms": 5_000}]}
        self.assertEqual(
            segmentation.build_request_plan(payload, file_count=1, requested_language="auto")["files"][0][0]["language"],
            "auto",
        )
        self.assertEqual(
            segmentation.build_request_plan(payload, file_count=1, requested_language="en")["files"][0][0]["language"],
            "English",
        )

    def test_hard_maximum_splits_long_turn(self) -> None:
        payload = {"duration_ms": 200_000, "speaker_turns": [{"start_ms": 0, "end_ms": 200_000, "speaker": "SPK_0"}]}
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual([item["end_ms"] - item["start_ms"] for item in plan["files"][0]], [90_000, 90_000, 20_000])

    def test_explicit_empty_vad_does_not_transcribe_the_entire_recording(self) -> None:
        payload = {"duration_ms": 600_000, "speech_regions": [], "speaker_turns": []}
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual(plan["files"], [[]])

    def test_missing_vad_keeps_full_audio_fallback(self) -> None:
        payload = {"duration_ms": 5_000}
        plan = segmentation.build_request_plan(payload, file_count=1, requested_language="auto")
        self.assertEqual([(v["start_ms"], v["end_ms"]) for v in plan["files"][0]], [(0, 5_000)])


class SpeakerBackendContractTests(unittest.TestCase):
    def test_worker_uses_the_maintained_funasr_diarization_backend(self) -> None:
        source = (ROOT / "segmentation-worker/app.py").read_text(encoding="utf-8")
        self.assertIn("ClusterBackend", source)
        self.assertIn("sv_chunk", source)
        self.assertIn("postprocess", source)
        self.assertNotIn("AgglomerativeClustering", source)
        self.assertNotIn("MAX_SPEAKER_CLUSTERS", source)

    def test_request_local_speaker_contract_is_explicit(self) -> None:
        compose = (ROOT.parents[1] / "deploy/compose.qwen.yml").read_text(encoding="utf-8")
        self.assertIn("SPEAKER_MERGE_THRESHOLD: ${SPEAKER_MERGE_THRESHOLD:-0.78}", compose)
        self.assertIn("SPEAKER_LOW_COHESION_COSINE: ${SPEAKER_LOW_COHESION_COSINE:-0.45}", compose)
        self.assertIn("SPEAKER_FALLBACK_MIN_WINDOWS: ${SPEAKER_FALLBACK_MIN_WINDOWS:-20}", compose)
        self.assertIn("SPEAKER_FALLBACK_COUNT: ${SPEAKER_FALLBACK_COUNT:-2}", compose)
        self.assertIn("MIN_SPEAKER_PROFILE_DURATION_MS: ${MIN_SPEAKER_PROFILE_DURATION_MS:-5000}", compose)

    def test_low_cohesion_single_cluster_uses_conservative_fallback(self) -> None:
        self.assertTrue(speaker_policy.should_apply_low_cohesion_fallback(
            window_count=184,
            raw_cluster_count=1,
            cohesion_median=0.148,
            minimum_windows=20,
            maximum_cohesion=0.45,
        ))

    def test_cohesive_or_short_single_cluster_does_not_use_fallback(self) -> None:
        self.assertFalse(speaker_policy.should_apply_low_cohesion_fallback(
            window_count=184,
            raw_cluster_count=1,
            cohesion_median=0.76,
            minimum_windows=20,
            maximum_cohesion=0.45,
        ))
        self.assertFalse(speaker_policy.should_apply_low_cohesion_fallback(
            window_count=12,
            raw_cluster_count=1,
            cohesion_median=0.10,
            minimum_windows=20,
            maximum_cohesion=0.45,
        ))


class ModelPreloadTests(unittest.TestCase):
    def test_gpu_preload_endpoints_acquire_admission_and_load(self) -> None:
        import ast
        import asyncio
        import threading
        from types import SimpleNamespace
        from typing import Any
        for worker in ("qwen-worker", "moss-worker"):
            path = ROOT / worker / "app.py"
            node = next(node for node in ast.parse(path.read_text()).body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == "load_models")
            node.decorator_list = []
            lock = threading.Lock()
            calls = []
            def load():
                self.assertTrue(lock.locked())
                calls.append("loaded")
            manager = SimpleNamespace(_admission_lock=lock, load=load, status=lambda: {"loaded": True})
            namespace = {"Any": Any, "asyncio": asyncio, "manager": manager, "HTTPException": RuntimeError}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
            result = asyncio.run(namespace["load_models"]())
            self.assertEqual(calls, ["loaded"])
            self.assertEqual(result["status"], "loaded")
            self.assertFalse(lock.locked())


class TimestampEvidenceTests(unittest.TestCase):
    def test_zero_duration_words_are_preserved_without_fabricated_extension(self) -> None:
        words = [{"text": "我", "start_ms": 100, "end_ms": 100}, {"text": "们", "start_ms": 180, "end_ms": 240}]
        self.assertEqual(timestamps.validated_word_spans(words, 300), words)

    def test_nonmonotonic_word_starts_make_alignment_unavailable(self) -> None:
        words = [{"text": "线", "start_ms": 80, "end_ms": 90}, {"text": "上", "start_ms": 50, "end_ms": 90}]
        self.assertEqual(timestamps.validated_word_spans(words, 100), [])

    def test_outside_or_reversed_word_intervals_are_not_clamped(self) -> None:
        for start, end in ((-1, 20), (100, 101), (50, 40)):
            self.assertEqual(timestamps.validated_word_spans([{"text": "word", "start_ms": start, "end_ms": end}], 100), [])

    def test_missing_or_invalid_aligner_evidence_keeps_text_and_omits_word_timing(self) -> None:
        import ast
        from types import SimpleNamespace
        from typing import Any
        path = ROOT / "qwen-worker/app.py"
        nodes = [node for node in ast.parse(path.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in {"_word_items", "_result_payload"}]
        namespace = {"Any": Any, "validated_word_spans": timestamps.validated_word_spans, "_engine": lambda: {}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        for boundary in (None, float("nan"), -0.1):
            source = SimpleNamespace(text="Keep these words.", language="English",
                time_stamps=SimpleNamespace(items=[SimpleNamespace(text="Keep", start_time=boundary, end_time=0.1)]))
            value = namespace["_result_payload"](source, 1000)
            self.assertEqual(value["text"], "Keep these words.")
            self.assertNotIn("words", value)
            self.assertNotIn("words", value["segments"][0])


class RollingContextTests(unittest.TestCase):
    def test_repeated_context_prefix_is_removed_with_words(self) -> None:
        words = [{"text": c, "start_ms": i * 40, "end_ms": (i + 1) * 40} for i, c in enumerate("有点三度其实我的头是凉我六月十四日")]
        text, repaired, removed = text_utils.trim_rolling_context_prefix(
            "有点三度。其实我的头是凉，我。", "有点三度。其实我的头是凉，我。六月十四日。", words
        )
        self.assertEqual(text, "六月十四日。")
        self.assertEqual("".join(item["text"] for item in repaired), "六月十四日")
        self.assertEqual(removed, 12)

    def test_real_repetition_inside_current_audio_is_retained(self) -> None:
        text = "预算三十万元。"
        words = [{"text": "预算三十万元", "start_ms": 24000, "end_ms": 27000}]
        value = text_utils.trim_rolling_context_prefix(text, text, words, maximum_removed_end_ms=24000)
        self.assertEqual(value, (text, words, 0))
        self.assertEqual(text_utils.trim_rolling_context_prefix(text, text, [], maximum_removed_end_ms=24000), (text, [], 0))

    def test_only_a_confirmed_padding_prefix_is_removed(self) -> None:
        words = [{"text": "预算三十万元", "start_ms": 23000, "end_ms": 24000},
                 {"text": "先测算", "start_ms": 24100, "end_ms": 26000}]
        text, kept, count = text_utils.trim_rolling_context_prefix(
            "预算三十万元。", "预算三十万元。先测算。", words, maximum_removed_end_ms=24000)
        self.assertEqual((text, kept, count), ("先测算。", words[1:], 6))


if __name__ == "__main__":
    unittest.main()
