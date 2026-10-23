import importlib.util
import ast
import asyncio
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("gpu_release", Path(__file__).parents[1] / "moss-worker/gpu_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def make_torch(self, *, initialized=True, clearable=True):
        state = {"reserved": 9978, "cleared": False}
        events = []
        def stats(device):
            return {"allocated_bytes.all.current": (0 if state['cleared'] else 32)*release.MIB,
                    "reserved_bytes.all.current": state['reserved']*release.MIB}
        def clear():
            events.append("workspaces")
            state['cleared'] = True
        def empty():
            events.append("cache")
            if state['cleared']:
                state['reserved'] = 0
        torch = SimpleNamespace(cuda=SimpleNamespace(is_initialized=lambda:initialized,
            memory_stats=stats, synchronize=lambda _:events.append("sync"), empty_cache=empty),
            _C=SimpleNamespace(_cuda_clearCublasWorkspaces=clear) if clearable else SimpleNamespace())
        return torch, state, events

    def test_workspace_cleanup_releases_pinned_large_segment(self):
        torch, state, events = self.make_torch()
        result = release.release_idle_cuda(torch, "cuda:0")
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['before']['allocated_mib'], 32)
        self.assertEqual(result['before']['reserved_mib'], 9978)
        self.assertEqual(result['after']['reserved_mib'], 0)
        self.assertEqual(events, ["sync", "cache", "workspaces", "cache"])

    def test_unavailable_cleanup_cannot_claim_success(self):
        torch, _, _ = self.make_torch(clearable=False)
        result = release.release_idle_cuda(torch, "cuda:0")
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['after']['reserved_mib'], 9978)

    def test_small_idle_pool_is_allowed_without_initializing_or_changing_workspaces(self):
        torch, state, events = self.make_torch()
        state['reserved'] = 64
        self.assertTrue(release.release_idle_cuda(torch, "cuda:0")['confirmed'])
        self.assertNotIn("workspaces", events)
        torch, _, events = self.make_torch(initialized=False)
        self.assertTrue(release.release_idle_cuda(torch, "cuda:0")['confirmed'])
        self.assertEqual(events, [])

    def test_real_manager_cannot_report_false_release_success_or_unload_busy_worker(self):
        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        source = Path(__file__).parents[1] / "moss-worker/app.py"
        tree = ast.parse(source.read_text())
        parts = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef))
                 and node.name in ("ModelManager", "unload_models")]
        for node in parts:
            node.decorator_list = []
        torch, _, _ = self.make_torch(clearable=False)
        namespace = dict(os=__import__("os"), torch=torch, threading=threading, time=time, Any=object,
                         GPUStage=lambda *args: None, DEVICE="cuda:0", asyncio=asyncio,
                         allocator_state=release.allocator_state, release_idle_cuda=release.release_idle_cuda,
                         IDLE_RESERVED_MIB=release.IDLE_RESERVED_MIB,
                         IDLE_UNLOAD_SECONDS=300, UNLOAD_AFTER_REQUEST=False,
                         JSONResponse=JSONResponse, HTTPException=HTTPException)
        exec(compile(ast.Module(body=parts, type_ignores=[]), str(source), "exec"), namespace)
        manager = namespace["ModelManager"]()
        self.addCleanup(manager._stop.set)
        namespace["manager"] = manager
        response = asyncio.run(namespace["unload_models"]())
        self.assertEqual(response.status_code, 503)
        self.assertTrue(manager.status()["resident"])
        manager._busy = True
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(namespace["unload_models"]())
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
