"""Bounded, read-only readiness reports. Never load models or repair services."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from . import __version__
from .store import Store, StoreBusy

SCOPE = "queue-worker-and-backend-discovery"
MAX_BODY = 64 * 1024
logger = logging.getLogger(__name__)
CODES = frozenset({
    "ready", "service_not_ready", "database_busy", "database_unavailable",
    "worker_absent", "worker_stale", "worker_backend_mismatch", "worker_version_mismatch",
    "worker_unavailable", "decoder_unavailable", "provider_unreachable", "provider_timeout",
    "provider_http_error", "provider_invalid_response", "provider_degraded",
    "provider_configuration_mismatch", "model_load_failed", "gpu_device_missing",
    "gpu_device_access_denied", "gpu_probe_tool_missing", "gpu_driver_library_mismatch",
    "gpu_nvml_unavailable", "gpu_probe_timeout", "gpu_probe_invalid_response", "gpu_probe_failed",
    "probe_timeout", "diagnostic_internal_error", "not_configured", "not_applicable", "dependency_failed",
})
COMPONENTS = frozenset({"service", "queue.database", "queue.worker", "speech.provider",
    "speech.configuration", "speech.asr", "speech.segmentation", "analysis.events",
    "analysis.vocal", "analysis.measurements"})
Code = Literal[*sorted(CODES)]
Component = Literal[*sorted(COMPONENTS)]


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    scope: Literal["queue-worker-and-backend-discovery"] = SCOPE
    code: Code
    component: Component
    available_workers: StrictInt | None = Field(default=None, ge=0)
    model_inference_verified: Literal[False] = False

    @model_validator(mode="after")
    def consistent_status(self):
        if (self.status == "ready") != (self.code == "ready"):
            raise ValueError("inconsistent_readiness_status")
        return self


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Component
    required: bool
    status: Literal["ok", "failed", "skipped"]
    code: Code | None = None
    action: Literal["check_container_gpu_access", "check_worker_presence", "check_queue_storage"] | None = None
    elapsed_ms: int = Field(default=0, ge=0)


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Component
    code: Code


class Report(Summary):
    schema_version: Literal["sonovect.readiness/v1"] = Field(default="sonovect.readiness/v1", alias="schema")
    observed_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T[0-9:.+\-]+Z?$", max_length=40)
    cache_age_ms: int = Field(default=0, ge=0)
    checks: list[Check]
    errors: list[Issue]
    warnings: list[Issue]


def check(component, required=True, code=None, *, skipped=False, elapsed_ms=0):
    component = component if component in COMPONENTS else "service"
    code = code if code in CODES else "diagnostic_internal_error" if code else None
    action = None
    if code and code.startswith("gpu_"):
        action = "check_container_gpu_access"
    elif code and code.startswith("worker_"):
        action = "check_worker_presence"
    elif code and code.startswith("database_"):
        action = "check_queue_storage"
    return Check(component=component, required=required, status="skipped" if skipped else "failed" if code else "ok",
                 code=code, action=action, elapsed_ms=elapsed_ms)


def report(checks, workers=None):
    errors = [Issue(component=c.component, code=c.code) for c in checks if c.required and c.status == "failed"]
    warnings = [Issue(component=c.component, code=c.code) for c in checks if not c.required and c.status == "failed"]
    primary = errors[0] if errors else Issue(component="service", code="ready")
    return Report(status="not_ready" if errors else "ready", code=primary.code, component=primary.component,
                  available_workers=workers, observed_at=datetime.now(timezone.utc).isoformat(),
                  checks=checks, errors=errors, warnings=warnings)


def summary(value):
    return Summary.model_validate({k: v for k, v in value.items() if k in Summary.model_fields}).model_dump()


async def fetch_health(url, timeout=4.5, headers=None, path="/health"):
    """A wall-clock deadline and streaming limit, in addition to HTTP phase limits."""
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=min(timeout, 4), trust_env=False, follow_redirects=False, headers=headers) as client:
                async with client.stream("GET", url + path) as response:
                    if response.status_code != 200:
                        return None, "provider_http_error"
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BODY:
                            return None, "provider_invalid_response"
        value = json.loads(content)
        if not isinstance(value, dict):
            return None, "provider_invalid_response"
        return value, None
    except (TimeoutError, httpx.TimeoutException):
        return None, "provider_timeout"
    except httpx.HTTPError:
        return None, "provider_unreachable"
    except (ValueError, UnicodeError):
        return None, "provider_invalid_response"


def upstream_code(value):
    if not isinstance(value, dict):
        return "provider_invalid_response"
    if value.get("reachable") is not True:
        code = value.get("error")
        return code if isinstance(code, str) and code in {"provider_unreachable", "provider_timeout", "provider_http_error", "provider_invalid_response"} else "provider_unreachable"
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return "provider_invalid_response"
    status = payload.get("status")
    if not isinstance(status, str):
        return "provider_invalid_response"
    if status in {"ok", "ready", "healthy"}:
        return None
    access = payload.get("gpu_access")
    if isinstance(access, dict) and access.get("available") is False:
        code = access.get("error")
        return code if isinstance(code, str) and code in CODES and code.startswith("gpu_") else "gpu_probe_failed"
    manager = payload.get("manager")
    if isinstance(manager, dict) and manager.get("last_load_error"):
        return "model_load_failed"
    return "provider_degraded"


def provider_checks(settings, value):
    status = value.get("status")
    if not isinstance(status, str) or status not in {"ok", "ready", "healthy", "degraded", "not_ready", "error"}:
        return [check("speech.provider", code="provider_invalid_response")]
    checks = [check("speech.provider")]
    expected = {"voice_analysis": settings.voice_enabled, "voice_measurements": settings.measurements_enabled}
    if "sound_analysis" in value:
        expected["sound_analysis"] = settings.sound_enabled
    mismatch = any(type(value.get(k, False)) is not bool or value.get(k, False) != v for k, v in expected.items())
    mismatch |= settings.voice_enabled and value.get("voice_backend", "moss") != settings.voice_backend
    checks.append(check("speech.configuration", code="provider_configuration_mismatch" if mismatch else None))
    upstreams = value.get("upstreams", {})
    if not isinstance(upstreams, dict):
        return checks + [check("speech.provider", code="provider_invalid_response")]
    known = [("qwen3_asr", "speech.asr", True, True),
             ("segmentation", "speech.segmentation", True, True),
             ("events", "analysis.events", False, settings.sound_enabled),
             ("vocal", "analysis.vocal", False, settings.voice_enabled),
             ("measurements", "analysis.measurements", False, settings.measurements_enabled)]
    for name, component, required, enabled in known:
        if not enabled:
            checks.append(check(component, required, "not_configured", skipped=True))
        elif name in upstreams:
            checks.append(check(component, required, upstream_code(upstreams[name])))
        elif not required:
            # External/older providers need not implement the internal component graph.
            checks.append(check(component, False, "not_applicable", skipped=True))
    if status not in {"ok", "ready", "healthy"} and not any(c.required and c.status == "failed" for c in checks):
        checks.append(check("speech.provider", code="provider_degraded"))
    return checks


class Readiness:
    def __init__(self, settings, cache_seconds=2, deadline=6):
        self.settings, self.cache_seconds, self.deadline = settings, cache_seconds, deadline
        self._task = None
        self._db_task = None
        self._cached = None
        self._cached_at = 0
        self._signature = None
        self._logged_at = 0

    async def collect(self):
        checks, workers = [], None
        pending = "queue.database"
        try:
            async with asyncio.timeout(self.deadline):
                started = time.monotonic()
                try:
                    if self._db_task is None or self._db_task.done():
                        self._db_task = asyncio.create_task(asyncio.to_thread(Store.worker_snapshot, self.settings, __version__))
                        # A timed-out waiter must not leave a raw background exception in logs.
                        self._db_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                    snapshot = await asyncio.shield(self._db_task)
                    workers = snapshot["available_workers"]
                    checks.extend([check("queue.database", elapsed_ms=int((time.monotonic()-started)*1000)),
                                   check("queue.worker", code=snapshot["code"])])
                except (OSError, StoreBusy) as error:
                    checks.extend([check("queue.database", code="database_busy" if isinstance(error, StoreBusy) else "database_unavailable"),
                                   check("queue.worker", code="dependency_failed", skipped=True)])
                except Exception:
                    checks.extend([check("queue.database", code="database_unavailable"),
                                   check("queue.worker", code="dependency_failed", skipped=True)])
                pending = "speech.provider"
                if self.settings.backend in {"speech", "vibevoice"}:
                    if self.settings.backend == "vibevoice":
                        from .auth import provider_headers
                        value, code = await fetch_health(self.settings.provider_url, headers=provider_headers(self.settings), path="/v1/models")
                        if not code:
                            models = value.get("data")
                            if not isinstance(models, list):
                                code = "provider_invalid_response"
                            elif not any(isinstance(m, dict) and m.get("id") == self.settings.vibevoice_model for m in models):
                                code = "provider_configuration_mismatch"
                        checks.append(check(pending, code=code))
                    else:
                        value, code = await fetch_health(self.settings.provider_url)
                        checks.extend([check(pending, code=code)] if code else provider_checks(self.settings, value))
                else:
                    checks.append(check(pending, code="not_applicable", skipped=True))
        except TimeoutError:
            checks.append(check(pending, code="probe_timeout"))
        except Exception:
            checks.append(check(pending, code="diagnostic_internal_error"))
        result = report(checks, workers)
        if len(result.model_dump_json(by_alias=True).encode()) > 32 * 1024:
            result = report([check("service", code="diagnostic_internal_error")])
        signature = (result.status, tuple((i.component, i.code) for i in result.errors + result.warnings))
        now = time.monotonic()
        if signature != self._signature or (result.status == "not_ready" and now-self._logged_at >= 300):
            logger.log(logging.WARNING if result.errors else logging.INFO,
                       "readiness status=%s code=%s component=%s errors=%s warnings=%s", result.status,
                       result.code, result.component, [(i.component, i.code) for i in result.errors],
                       [(i.component, i.code) for i in result.warnings])
            self._signature, self._logged_at = signature, now
        self._cached, self._cached_at = result, now
        return result

    async def get(self):
        now = time.monotonic()
        if self._cached is not None and now-self._cached_at < self.cache_seconds:
            result = self._cached
        else:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self.collect())
            # One disconnected caller must not cancel other callers' shared collection.
            result = await asyncio.shield(self._task)
        return result.model_copy(update={"cache_age_ms": max(0, int((time.monotonic()-self._cached_at)*1000))}).model_dump(by_alias=True)

    async def close(self):
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
