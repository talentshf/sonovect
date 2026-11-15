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
from .remote_input import download_source
from .recognition import speech_evidence

logger = logging.getLogger(__name__)


def resume_options(options, transcript, previous):
    selected = dict(options)
    if transcript is not None:
        selected.update(transcribe=False, timestamps="none", context="", hotwords=[], speakers=False)
    for flag, stage in (("analyze_sound", "events"), ("analyze_voice", "vocal"),
                        ("measure_voice", "measurements"), ("detect_speech", "speech_activity")):
        if previous.get("stages", {}).get(stage, {}).get("status") == "completed":
            selected[flag] = False
    return selected


def merge_analysis(previous, current):
    from copy import deepcopy
    result = deepcopy(current)
    fields = {"events": ["events"], "vocal": ["emotions", "voice"], "measurements": ["measurements"],
              "speech_activity": ["speech_regions"], "diarization": ["speaker_turns"], "classification": ["classification"], "understanding": ["understanding"], "alignment": ["alignment"]}
    for name, stage in previous.get("stages", {}).items():
        result.setdefault("stages", {}).setdefault(name, stage)
        if stage["status"] != "completed":
            continue
        result.setdefault("stages", {})[name] = stage
        for field in fields.get(name, []):
            result[field] = previous.get(field, [])
        if name in (previous.get("engines") or {}):
            if result.get("engines") is None:
                result["engines"] = {}
            result["engines"][name] = previous["engines"][name]
    states = [v["status"] for v in result.get("stages", {}).values() if v["status"] != "not_requested"]
    if result.get("stages"):
        result["status"] = ("not_requested" if not states else "completed" if all(s == "completed" for s in states)
                            else "failed" if all(s == "failed" for s in states) else "partial")
    if result["status"] == "completed":
        result.pop("error", None)
    return result


class Worker:
    def __init__(self, settings, backend=None, downloader=download_source, translator=None):
        self.settings = settings
        self.store = Store(settings)
        self.backend = backend or build_backend(settings)
        self.downloader = downloader
        from .upstreams import translate
        self.translate = translator or translate
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
        def notifications():
            from .delivery import deliver_one
            while not stopping.is_set():
                try:
                    if deliver_one(self.store):
                        continue
                except Exception:
                    logger.warning("Notification outbox unavailable; will retry")
                stopping.wait(1)
        delivery = threading.Thread(target=notifications, name="completion-delivery", daemon=True)
        delivery.start()
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
            delivery.join(timeout=12)
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
        results = job["result"] or []
        analysis = job["analysis"] or []
        evidence = job["evidence"] or []
        translations = job["translation"] or []
        sources = job["sources"]
        def remember_speech(result, item):
            if job["protocol"] and not result["text"].strip():return
            index=next((i for i,x in enumerate(results) if x["key"]==result["key"]),None)
            if index is None:
                results.append(result);evidence.append(item)
            else:
                results[index]=result;evidence[index]=item

        try:
            if job["options"].get("channel_mode") == "independent":
                from .media import inspect_media
                expanded = []
                for source in sources:
                    if "channel" in source or source.get("error") == "channel_inspection_failed":
                        expanded.append(source)
                        continue
                    try:
                        _, stream, _ = inspect_media(Path(source["path"]),job["options"],self.settings)
                        channels = stream.get("channels", 0)
                        if type(channels) is not int or not 1 <= channels <= 8:
                            raise MediaError("media_channel_limit")
                        expanded.extend({**source,"key":source["key"]+"_ch"+str(channel),"channel":channel} for channel in range(channels))
                    except Exception:
                        expanded.append({**source,"status":"failed","error":"channel_inspection_failed"})
                sources = expanded
                if not self.store.expand_sources(job["id"],self.owner,sources):
                    return True
            for source in sources:
                current = self.store.get(job["id"])
                if current["state"] != "running" or current["lease_owner"] != self.owner:
                    break
                if source["status"] == "succeeded" or source.get("error") == "channel_inspection_failed":
                    continue
                old_result = next((x for x in results if x["key"] == source["key"]), None)
                old_analysis = next((x for x in analysis if x["key"] == source["key"]), {})
                selected = resume_options(job["options"], old_result, old_analysis)
                try:
                    if job["protocol"]:
                        if job["engine"]["identity"] != self.backend.identity():
                            raise MediaError("engine_configuration_mismatch")
                        source.update(self.downloader(self.settings, source))
                        self.store.materialized(job["id"], self.owner, sources)
                    original = Path(source["path"])
                    def progress(event):
                        if event.get("stage")=="speech.completed":
                            if job["protocol"] and not event["result"]["text"].strip():return
                            remember_speech(event["result"],event["evidence"])
                            source["status"]="running"
                            self.store.checkpoint(job["id"],self.owner,sources,results,analysis,evidence,source["key"],translations,stage="speech")
                        else:
                            self.store.progress(job["id"],self.owner,{**event,"source":source["key"]})
                    stage_started = time.monotonic()
                    with prepare_media(original, {**job["options"], **({"audio_channel":source["channel"]} if "channel" in source else {})}, self.settings, scratch_dir=original.parent) as (path, metadata):
                        media_seconds += time.monotonic() - stage_started
                        source["media"] = metadata
                        stage_started = time.monotonic()
                        try:
                            if not any(selected.get(k) for k in ("transcribe", "speakers", "detect_speech", "analyze_sound", "analyze_voice", "measure_voice")):
                                from .recognition import Recognition
                                recognition = Recognition(None, {"key": source["key"], "status": "not_requested"}, {})
                            elif hasattr(self.backend, "process_stream"):
                                recognition = self.backend.process_stream(path, source["key"], selected,
                                    progress)
                            else:
                                recognition = self.backend.process(path, source["key"], selected)
                            result, extra = recognition
                            if result is not None:
                                remember_speech(result,getattr(recognition,"evidence",None) or speech_evidence({},result))
                            if job["protocol"]:
                                if job["engine"]["identity"] != self.backend.identity():
                                    raise MediaError("engine_configuration_mismatch")
                                if not result["text"].strip():
                                    raise MediaError("ASR_RESPONSE_HAVE_NO_WORDS")
                        finally:
                            processing_seconds += time.monotonic() - stage_started
                        result = result or old_result
                        extra = merge_analysis(old_analysis, extra)
                        analysis = [x for x in analysis if x["key"] != source["key"]]
                        analysis.append(extra)
                        if selected.get("classify_audio") or selected.get("audio_question") or selected.get("alignment_text"):
                            source["status"] = "running"
                            if not self.store.checkpoint(job["id"], self.owner, sources, results, analysis, evidence,
                                                         source["key"], translations, stage="speech" if result else "media"):
                                break
                            from .audio_tasks import run as run_audio_tasks
                            def save_audio_stage(value,stage):
                                old_analysis.clear();old_analysis.update(value)
                                analysis[:]=[x for x in analysis if x["key"]!=source["key"]]+[value]
                                if not self.store.checkpoint(job["id"],self.owner,sources,results,analysis,evidence,source["key"],translations,stage=stage):
                                    raise MediaError("job_ownership_lost")
                            extra = run_audio_tasks(self.settings,path,metadata,selected,old_analysis,extra,on_stage=save_audio_stage)
                            analysis = [x for x in analysis if x["key"] != source["key"]] + [extra]
                        if job["options"].get("translate_to") and result is not None:
                            # Save successful speech before the optional language service runs.
                            source["status"] = "running"
                            if not self.store.checkpoint(job["id"], self.owner, sources, results, analysis, evidence,
                                                         source["key"], translations, stage="speech"):
                                break
                            previous = next((x for x in translations if x["key"] == source["key"]), None)
                            translated = self.translate(self.settings, result, job["options"]["translate_to"],
                                (evidence[results.index(result)].get("language") if evidence else None), previous,
                                job["options"].get("translation_context", ""))
                            translations = [x for x in translations if x["key"] != source["key"]] + [translated]
                        if result is None and extra["status"] in {"failed", "not_requested"}:
                            source["status"], source["error"] = "failed", extra.get("error") or "analysis_processing_failed"
                        else:
                            source["status"] = "succeeded" if extra["status"] not in {"failed", "partial"} else "partial"
                except Exception as error:
                    # Provider exceptions may contain paths, transcript snippets or credentials.
                    logger.warning("Source processing failed for job %s, source %s", job["id"], source["key"])
                    from .upstreams import UpstreamError
                    code = str(error) if isinstance(error, (MediaError, UpstreamError)) else "processing_failed"
                    retained = any(x["key"] == source["key"] for x in results) or any(v["status"] == "completed" for v in old_analysis.get("stages", {}).values())
                    source["status"], source["error"] = "partial" if retained else "failed", code
                    if isinstance(error, UpstreamError) and job["options"].get("translate_to"):
                        translations = [x for x in translations if x["key"] != source["key"]] + [{
                            "key": source["key"], "status": "failed", "language": job["options"]["translate_to"], "error": code}]
                    else:
                        from .models import Analysis
                        analysis = [x for x in analysis if x["key"] != source["key"]]
                        analysis.append(merge_analysis(old_analysis, Analysis(key=source["key"], status="failed", error=code).model_dump(mode="json", exclude_none=True)))
                if not self.store.checkpoint(job["id"], self.owner, sources, results, analysis, evidence, source["key"], translations):
                    break
            states = [s["status"] for s in sources]
            state = "succeeded" if all(s == "succeeded" for s in states) else "partial" if any(s in {"succeeded", "partial"} for s in states) else "failed"
            self.store.finish(job["id"], self.owner, state, sources, results, analysis,
                              (sources[0].get("error") if job["protocol"] else "processing_failed") if state == "failed" else None,
                              evidence=evidence or None, translation=translations or None)
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
