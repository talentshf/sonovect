# HTTP API

API version: `/v1`. Product version:0.3.0. Authentication is an operator-supplied bearer token. An installation is one trust domain: one token can access all its jobs. Do not expose model-service ports.

An opt-in [DashScope-compatible asynchronous file interface](filetrans-compatibility.md) provides `/api/v1` submission, polling and signed results over the same task store. It is a single-file protocol subset; enable it explicitly with the documented controlled input hosts and persistent signing key.

The optional authenticated WebSocket `/v1/realtime` supports Qwen and VibeVoice-ASR Streaming 1.5B in a separate runtime. It is disabled by default, with transient client-owned sessions rather than durable file jobs. See the [realtime protocol, limits and runtime setup](vibevoice-realtime.md).

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Process liveness |
| GET | `/ready` | Required worker/provider discovery; not model accuracy |
| GET | `/v1/capabilities` | Current options, limits, outputs, optional capabilities and `execution.layout` |
| POST | `/v1/jobs` | Multipart `files` plus JSON `options`; returns202 and job ID |
| GET | `/v1/jobs/{id}` | State, source details and options |
| POST | `/v1/jobs/{id}/cancel` | Cancel publication; active inference may finish internally |
| POST | `/v1/jobs/{id}/retry` | Explicit reprocessing while original inputs remain |
| GET | `/v1/jobs/{id}/result?format=json` | Speech results; `format` accepts `json`, `text` or `srt` |
| GET | `/v1/jobs/{id}/analysis` | Independent staged analysis |
| GET | `/v1/jobs/{id}/manifest` | Output artifact hashes and metadata; input hashes are in job status |

The [generated OpenAPI](../contracts/openapi-v1.json) is the exact maintained interface; [job options](../contracts/job-options.schema.json) defines strict inputs. `Idempotency-Key` provides exact admission deduplication. File paths on the server are never selected by uploaded names. Unknown options, unsupported capabilities, invalid media limits and unauthenticated requests fail explicitly.

Status belongs to the job endpoint; result JSON is a source list without a service-specific text wrapper. [Results](results.md) documents the independent analysis schema and partial failures. [Usage](usage.md) covers state transitions, retention and export.

`GET /v1/diagnostics/readiness` returns authenticated component diagnostics with the same 200/503 readiness decision as `/ready`. The public summary adds `code`, `component` and a nullable `available_workers`; failures also retain `model_inference_verified: false`. See [readiness diagnostics](readiness.md) for error codes, freshness, deadlines and compatibility.
