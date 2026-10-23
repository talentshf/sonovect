"""A compact deployment must supervise failures and retain opt-in boundaries."""
import itertools
import os
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from sonovect.runtime import child_environment, processes, serve, terminate
from sonovect.setup import selection


class CompactRuntimeTests(unittest.TestCase):
    def test_every_selection_preserves_models_and_reduces_deployment_units(self):
        for route, sound, voice, measure in itertools.product(
                ["cpu", "qwen"], ["none", "ast"], ["none", "emotion2vec", "4b", "8b"], [False, True]):
            compact = selection(route=route, sound=sound, voice=voice, measurements=measure)
            distributed = selection(route=route, sound=sound, voice=voice, measurements=measure, layout="distributed")
            self.assertEqual(compact["models"], distributed["models"])
            self.assertEqual(compact["download_bytes"], distributed["download_bytes"])
            self.assertEqual(compact["container_count"], 2 + int(sound == "ast" or voice == "emotion2vec" or measure) + int(voice in {"4b", "8b"}))
            self.assertLessEqual(compact["container_count"], 4)
            env = compact["environment"]
            if sound == "ast" or voice == "emotion2vec" or measure:
                names = {p.name for p in processes("analysis", env)}
                self.assertEqual(names, ({"events"} if sound == "ast" else set()) | ({"vocal"} if voice == "emotion2vec" else set()) | ({"measurements"} if measure else set()))
            else:
                with self.assertRaisesRegex(ValueError, "no_selected"):
                    processes("analysis", env)
            if measure and sound == "none" and voice != "emotion2vec":
                self.assertEqual(env["SONOVECT_ANALYSIS_TARGET"], "analysis-measurements")

    def test_model_cache_namespaces_and_private_ports_are_separate(self):
        env = {"SEGMENTATION_CACHE": "/seg", "QWEN_HF_HOME": "/qwen", "HF_HOME": "/wrong"}
        self.assertEqual(child_environment("qwen", "segmentation", env)["MODELSCOPE_CACHE"], "/seg")
        self.assertEqual(child_environment("qwen", "asr", env)["HF_HOME"], "/qwen")
        for spec in processes("qwen"):
            command = spec.command()
            self.assertEqual(command[command.index("--host") + 1], "0.0.0.0" if spec.name == "provider" else "127.0.0.1")

    def test_child_exit_fails_unit_and_cleans_remaining_children(self):
        children = [Mock(), Mock(), Mock()]
        for c in children:
            c.poll.return_value = None
        # Startup ready, then a model child dies. The queue process cannot stay orphaned.
        children[0].poll.side_effect = [None, 7, 7]
        worker = Mock();worker.poll.return_value = None
        with patch("sonovect.runtime.subprocess.Popen", side_effect=[*children, worker]), \
             patch("sonovect.runtime.healthy", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "runtime_child_exited:segmentation"):
                serve("qwen", threading.Event(), grace=0.01)
        worker.terminate.assert_called_once()
        children[1].terminate.assert_called_once()
        children[2].terminate.assert_called_once()

    def test_startup_failure_never_claims_queue_jobs(self):
        children = [Mock(), Mock(), Mock()]
        for c in children:c.poll.return_value = 1
        with patch("sonovect.runtime.subprocess.Popen", side_effect=children) as spawn:
            with self.assertRaisesRegex(RuntimeError, "during_startup"):
                serve("qwen", threading.Event())
        self.assertEqual(spawn.call_count, 3)

    def test_shutdown_drains_worker_before_model_helpers_and_kills_hung_child(self):
        order = []
        helper, worker = Mock(), Mock()
        for c in [helper, worker]:c.poll.return_value = None
        worker.terminate.side_effect = lambda: order.append("worker")
        helper.terminate.side_effect = lambda: order.append("helper")
        worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 0.01), 0]
        terminate([("helper", helper), ("worker", worker)], grace=0.01)
        self.assertEqual(order, ["worker", "helper"])
        worker.kill.assert_called_once()


if __name__ == "__main__":unittest.main()
