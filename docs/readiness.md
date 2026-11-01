# Readiness diagnostics

`/health` is process liveness. `/ready` checks the durable queue, recent matching worker presence and required backend discovery. It never submits a job, loads weights or proves inference/accuracy. Idle model unloading and normal busy workers are not failures. A configured optional analysis service can fail with a warning while basic speech remains ready; mismatched deployment capability declarations still fail readiness.

| Entry | Result |
| --- | --- |
| `GET /ready` | Unauthenticated safe summary, HTTP 200 when ready or 503 otherwise |
| `GET /v1/diagnostics/readiness` | Same 200/503 decision with existing bearer authentication; component checks, errors, warnings and observation time |
| `sonovect ready` | JSON summary on stdout, exit 0 ready / 1 not ready |
| `sonovect ready --details` | Authenticated component report; an older server falls back to summary with `details_supported: false` |
| MCP `sonovect_ready(details=false)` | Same read-only report; `not_ready` is a diagnostic result, not a failed tool invocation |
| `sonovect-health` / `sonovect-runtime --check` | Structured container health output with component/code and exit 0/1 |

A GPU device access failure can return:

```json
{"status":"not_ready","scope":"queue-worker-and-backend-discovery","code":"gpu_device_access_denied","component":"speech.asr","available_workers":1,"model_inference_verified":false}
```

Existing `status`, `scope` and successful-response fields keep their meaning. The additional `code` and logical `component` are stable machine-readable fields. `available_workers` is null if queue presence could not be read, not a fabricated zero. Diagnostics schema is `sonovect.readiness/v1`; the checked contracts are [summary](../contracts/readiness-summary.schema.json) and [detail](../contracts/readiness.schema.json).

Detailed checks are `ok`, `failed` or `skipped`. A skipped check has a reason (`not_configured`, `not_applicable`, `dependency_failed`). `errors` includes all observed required failures, `warnings` optional failures. The primary code is selected in queue/database, worker, transport/protocol, configuration and required-component order. It is a first investigation target, not a claim that only one root cause exists. Old/external providers without component details fall back to a bounded provider failure, never invented hardware attribution.

| Codes | What to inspect |
| --- | --- |
| `database_busy`, `database_unavailable` | Queue storage and current lock holders; do not overwrite the database |
| `worker_absent`, `worker_stale`, `worker_backend_mismatch`, `worker_version_mismatch`, `worker_unavailable` | Worker process, heartbeat freshness, configured backend and installed version |
| `provider_unreachable`, `provider_timeout`, `provider_http_error`, `provider_invalid_response` | Configured internal service, reachability, response status/schema and deadline |
| `provider_degraded`, `provider_configuration_mismatch`, `model_load_failed` | Provider state, configuration agreement and existing model load failures |
| `gpu_device_missing`, `gpu_device_access_denied`, `gpu_probe_tool_missing` | Host/container device availability, device authorization or missing diagnostic executable |
| `gpu_driver_library_mismatch`, `gpu_nvml_unavailable` | Driver/library agreement and NVIDIA management-library availability |
| `gpu_probe_timeout`, `gpu_probe_invalid_response`, `gpu_probe_failed` | Bounded GPU discovery; these do not establish a model or hardware failure |
| `probe_timeout`, `diagnostic_internal_error` | A diagnostic could not complete; do not treat it as ready |
| `service_not_ready` | Compatibility fallback for a server without detailed failure codes |

For a GPU access error, compare host and container device access and inspect the native container configuration. Recreating an affected worker may restore device access, but first check active jobs and the recovery point using the deployment's existing management procedure. A diagnostic must not automatically restart containers, reload drivers, alter host permissions or retry jobs. A permission error does not establish which host event caused it.

Provider checks run concurrently with a 4.5-second aggregate deadline; each internal request is bounded to 4 seconds and 64 KiB. Public readiness has a 6-second aggregate deadline; queue diagnostic lock waiting is 250 milliseconds. These settings do not change job transaction/recovery timeouts. The health client waits up to 8 seconds, below its container-check timeout. GPU tool execution is limited to 3 seconds and 8 KiB, with timed-out/oversized subprocesses reaped.

Concurrent callers share one collection per service process. The API caches completed reports for at most 2 seconds; the coordinator only shares an in-flight collection, so finished cache lifetimes do not accumulate across layers. Authenticated reports include collection completion time `observed_at` and report `cache_age_ms`; these do not claim an instantaneous GPU sample. Expired cache entries are not used as a fallback for failed refreshes. State/error changes log immediately, repeated identical required failures at most once per 5 minutes. Diagnostics expose fixed codes and whitelisted fields, not tokens, addresses, paths, original exceptions or transcripts.
