"""Dedicated queue worker. Inference is never tied to an HTTP request lifetime."""
from pathlib import Path
import json
import os
import logging
import signal
import threading
import time
import uuid
from .backends import build_backend
from .config import Settings
from .media import MediaError, decoder_available, prepare_media
from .store import Store, StoreBusy
from . import __version__

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, backend=None):
        self.settings = settings
        self.store = Store(settings)
        self.backend = backend or build_backend(settings)
        self.owner = uuid.uuid4().hex
        self._next_prune = 0.0

    def announce(self):
        available = decoder_available() and getattr(self.backend, "available", lambda: True)()
        self.store.worker_seen(self.owner, self.settings.backend, __version__, available)

    def serve(self, stopping):
        health_file = Path(os.getenv("SONOVECT_WORKER_HEALTH_FILE", "/tmp/sonovect-worker.json"))
        health_file.write_text(json.dumps({"owner": self.owner}))
        try:
            self.announce()
        except StoreBusy:
            logger.warning("Worker presence database busy; presence will retry")
        def report():
            while not stopping.wait(min(10, self.settings.worker_stale_seconds / 3)):
                try:
                    self.announce()
                except Exception:
                    logger.warning("Worker presence update failed")
        presence = threading.Thread(target=report, name="worker-presence", daemon=True)
        presence.start()
        try:
            while not stopping.is_set():
                try:
                    worked = self.run_once()
                except StoreBusy:
                    # A transient writer is not a failed model/runtime. A job
                    # already claimed keeps its lease and is recoverable by
                    # the existing ownership/expiry checks.
                    logger.warning("Queue database busy; waiting before retry")
                    stopping.wait(max(.1, self.settings.poll_seconds))
                    continue
                if not worked:
                    stopping.wait(self.settings.poll_seconds)
        finally:
            stopping.set()
            presence.join()
            try:
                self.store.worker_departed(self.owner)
            except StoreBusy:
                logger.warning("Worker departure database busy; presence will expire")
            finally:
                health_file.unlink(missing_ok=True)

    def run_once(self):
        # Faster queue pickup must not scan every retained result ten times a
        # second. Artifact reads still enforce expiry immediately in the API.
        now = time.monotonic()
        if now >= self._next_prune:
            self.store.prune()
            self._next_prune = now + min(60, self.settings.input_ttl_hours * 3600,
                                         self.settings.result_ttl_hours * 3600)
        job = self.store.claim(self.owner)
        if job is None:
            return False
        started = time.monotonic()
        media_seconds = processing_seconds = 0.0
        stop = threading.Event()
        def renew():
            while not stop.wait(self.settings.lease_seconds / 3):
                try:
                    if not self.store.heartbeat(job["id"], self.owner):
                        return
                except Exception:
                    logger.warning("Lease renewal failed for job %s", job["id"])
        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        results, analysis = [], []
        sources = job["sources"]
        try:
            for source in sources:
                current = self.store.get(job["id"])
                if current["state"] != "running" or current["lease_owner"] != self.owner:
                    break
                try:
                    original = Path(source["path"])
                    stage_started = time.monotonic()
                    with prepare_media(original, job["options"], self.settings, scratch_dir=original.parent) as (path, metadata):
                        media_seconds += time.monotonic() - stage_started
                        source["media"] = metadata
                        stage_started = time.monotonic()
                        try:
                            result, extra = self.backend.process(path, source["key"], job["options"])
                        finally:
                            processing_seconds += time.monotonic() - stage_started
                    results.append(result)
                    analysis.append(extra)
                    source["status"] = "succeeded" if extra["status"] not in {"failed", "partial"} else "partial"
                except Exception as error:
                    # Provider exceptions may contain paths, transcript snippets or credentials.
                    logger.warning("Source processing failed for job %s, source %s", job["id"], source["key"])
                    code = str(error) if isinstance(error, MediaError) else "processing_failed"
                    source["status"], source["error"] = "failed", code
                    from .models import Analysis
                    analysis.append(Analysis(key=source["key"], status="failed", error=code).model_dump(mode="json", exclude_none=True))
            states = [s["status"] for s in sources]
            state = "succeeded" if all(s == "succeeded" for s in states) else "partial" if results else "failed"
            self.store.finish(job["id"], self.owner, state, sources, results, analysis,
                              "processing_failed" if state == "failed" else None)
        finally:
            stop.set()
            heartbeat.join()
            logger.info("job_timing id=%s queue_s=%s media_s=%.4f processing_s=%.4f worker_s=%.4f",
                        job["id"], job.get("_queue_seconds"), media_seconds,
                        processing_seconds, time.monotonic() - started)
        return True


def main():
    logging.basicConfig(level=logging.INFO)
    worker = Worker(Settings.from_env())
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    worker.serve(stopping)


if __name__ == "__main__":
    main()
