from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT
COMPOSE = ROOT.parents[1] / "deploy" / "compose.qwen.yml"


class SpeechContractTests(unittest.TestCase):
    def test_compose_has_only_new_runtime_names(self) -> None:
        source = COMPOSE.read_text(encoding="utf-8")
        for value in (
            "sonovect-runtime",
            "local-worker",
            "analysis:",
            "speech-sound",
        ):
            self.assertIn(value, source)
        self.assertNotIn("sense" + "voice", source.lower())
        self.assertNotIn("leg" + "acy", source.lower())

    def test_api_exposes_required_routes_without_retired_upstream(self) -> None:
        source = (RUNTIME / "api" / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        routes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and decorator.args:
                        value = decorator.args[0]
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            routes.add(value.value)
        for route in ("/health", "/models", "/transcribe", "/transcribe/full"):
            self.assertIn(route, routes)
        self.assertNotIn("/ws/transcribe", routes)
        self.assertNotIn("/extract_text", routes)
        self.assertNotIn("leg" + "acy", source.lower())


    def test_models_are_pinned(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("bcd2b5b7f32b480ab5790554cfa8347f246a14f3", compose)
        self.assertIn("c07281df297b9905d24a508279258cccf987a064", compose)
        self.assertIn("6907a499dc0e87cc77c8ae0fe23fd0eb5476a02d", compose)
        self.assertIn("5cbb1d823937cd5b5de3d8fa4d3a7253ebd3b883", compose)

    def test_enrichment_schema_is_sonovect_v2(self) -> None:
        source = (RUNTIME / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn('"schema_version": "sonovect/v2"', source)
        self.assertIn('"acoustic": _lane_state', source)
        self.assertIn('"stage_payloads"', source)
        self.assertNotIn("sense" + "voice-enrichment", source)



    def test_gpu_pipeline_is_serialized_and_capacity_gated(self) -> None:
        api = (RUNTIME / "api" / "app.py").read_text(encoding="utf-8")
        qwen = (RUNTIME / "qwen-worker" / "app.py").read_text(encoding="utf-8")
        moss = (RUNTIME / "moss-worker" / "app.py").read_text(encoding="utf-8")
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("GPU_PIPELINE_LOCK = asyncio.Lock()", api)
        self.assertIn("async with GPU_PIPELINE_LOCK", api)
        self.assertIn("torch.cuda.mem_get_info", qwen)
        self.assertIn("torch.cuda.mem_get_info", moss)
        self.assertIn("QWEN_MIN_FREE_GIB: ${QWEN_MIN_FREE_GIB:-6}", compose)
        self.assertIn("MOSS_MIN_FREE_GIB: ${MOSS_MIN_FREE_GIB:-10}", compose)


if __name__ == "__main__":
    unittest.main()
