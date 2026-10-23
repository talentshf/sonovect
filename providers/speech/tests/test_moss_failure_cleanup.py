from __future__ import annotations

import importlib.util
import gc
from pathlib import Path
import traceback
import unittest
import weakref


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "moss-worker/failure_cleanup.py"
)
SPEC = importlib.util.spec_from_file_location("moss_failure_cleanup", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FailureCleanupTests(unittest.TestCase):
    def test_detach_exception_releases_traceback_and_chaining(self):
        root = RuntimeError("root")
        try:
            raise RuntimeError("CUDA out of memory") from root
        except RuntimeError as error:
            self.assertIsNotNone(error.__traceback__)
            self.assertIs(error.__cause__, root)
            message = MODULE.detach_exception(error)
            self.assertEqual(message, "CUDA out of memory")
            self.assertIsNone(error.__traceback__)
            self.assertIsNone(error.__cause__)
            self.assertIsNone(error.__context__)

    def test_formatted_diagnostic_preserves_evidence_without_retaining_graph(self):
        class Graph:pass
        references=[]
        def failed_load():
            graph=Graph();references.append(weakref.ref(graph))
            raise RuntimeError('allocation failed')
        try:
            failed_load()
        except RuntimeError as error:
            gc.collect();self.assertIsNotNone(references[0]())
            diagnostic=''.join(traceback.format_exception(error))
            MODULE.detach_exception(error)
            gc.collect();self.assertIsNone(references[0]())
            self.assertIn('failed_load',diagnostic)
            self.assertIn('allocation failed',diagnostic)
