"""Supervise the selected local processes as one deployment unit.

Model processes keep separate Python state and lazy model lifetimes. Qwen's
private HTTP hops stay on loopback; analysis ports stay on the private bridge.
An unexpected child exit stops the unit, so Compose can restart it without
leaving an apparently healthy orphan queue worker.
"""
import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)
PROVIDERS = Path("/opt/sonovect/providers")


@dataclass(frozen=True)
class Process:
    name: str
    module: str
    port: int
    private: bool = True

    def command(self):
        return [sys.executable, "-m", "uvicorn", self.module, "--app-dir",
                str(PROVIDERS / self.name), "--host", "127.0.0.1" if self.private else "0.0.0.0",
                "--port", str(self.port), "--no-server-header"]


def enabled(name, environ):
    value = environ.get(name, "false").lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError("invalid_configuration:" + name)
    return value in {"true", "1", "yes"}


def processes(role, environ=None):
    env = os.environ if environ is None else environ
    if role == "qwen":
        return [Process("segmentation", "app:app", 8082),
                Process("asr", "app:app", 8081), Process("provider", "app:app", 8080, False)]
    if role != "analysis":
        raise ValueError("unknown_runtime_role")
    selected = []
    if enabled("SONOVECT_SOUND_ENABLED", env):
        selected.append(Process("events", "app:app", 8084, False))
    if enabled("SONOVECT_VOICE_ENABLED", env) and env.get("SONOVECT_VOICE_BACKEND") == "emotion2vec":
        selected.append(Process("vocal", "vocal_app:app", 8085, False))
    if enabled("SONOVECT_MEASUREMENTS_ENABLED", env):
        selected.append(Process("measurements", "measurement_app:app", 8086, False))
    if not selected:
        raise ValueError("analysis_runtime_has_no_selected_modules")
    return selected


def child_environment(role, name, environ=None):
    env = dict(os.environ if environ is None else environ)
    env["PYTHONPATH"] = str(PROVIDERS / name) + os.pathsep + env.get("PYTHONPATH", "")
    if role == "qwen":
        if name == "segmentation":
            env["MODELSCOPE_CACHE"] = env.get("SEGMENTATION_CACHE", "/models/segmentation")
            env["HF_HOME"] = env.get("SEGMENTATION_HF_HOME", "/models/segmentation/huggingface")
        elif name == "asr":
            env["HF_HOME"] = env.get("QWEN_HF_HOME", "/models/qwen/huggingface")
    return env


def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except Exception:
        return False


def terminate(children, grace=60):
    # Ask the queue worker to finish first; helpers remain alive during drain.
    for _, child in reversed(children):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def serve(role, stopping, startup_timeout=180, grace=60):
    specs = processes(role)
    children = []
    try:
        for spec in specs:
            children.append((spec.name, subprocess.Popen(spec.command(), env=child_environment(role, spec.name))))
        deadline = time.monotonic() + startup_timeout
        while not stopping.is_set():
            if any(child.poll() is not None for _, child in children):
                raise RuntimeError("runtime_child_exited_during_startup")
            if all(healthy(spec.port) for spec in specs):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("runtime_startup_timeout")
            stopping.wait(0.5)
        if role == "qwen" and not stopping.is_set():
            children.append(("worker", subprocess.Popen([sys.executable, "-m", "sonovect.worker"])))
        while not stopping.wait(0.5):
            dead = next((name for name, child in children if child.poll() is not None), None)
            if dead:
                raise RuntimeError("runtime_child_exited:" + dead)
        return 0
    finally:
        terminate(children, grace)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["qwen", "analysis"])
    parser.add_argument("--check", action="store_true", help="Probe all selected processes without loading models")
    args = parser.parse_args(argv)
    if args.check:
        if not all(healthy(s.port) for s in processes(args.role)):
            return 1
        if args.role == "qwen":
            from .health import main as worker_health
            return worker_health(["worker"])
        return 0
    logging.basicConfig(level=logging.INFO)
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        return serve(args.role, stopping)
    except Exception:
        logger.exception("Selected runtime stopped")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
