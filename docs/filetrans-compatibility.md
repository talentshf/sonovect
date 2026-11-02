# Compatible asynchronous file transcription

This opt-in interface implements the single-file DashScope asynchronous ASR
protocol. It uses the existing durable task store and one recognition, with
separate native and compatible result views. It does not implement the FunASR
WebSocket protocol, synchronous recognition, vendor uploads, billing or vocabulary
resource management. The native `/v1` interface remains available.

[中文说明](filetrans-compatibility.zh-CN.md) · [OpenAPI](../contracts/openapi-v1.json)

| Method | Path | Authorization |
| --- | --- | --- |
| GET | `/api/v1/models` | Service bearer token; model capabilities and limits |
| POST | `/api/v1/services/audio/asr/transcription` | Service bearer token and `X-DashScope-Async: enable` |
| GET | `/api/v1/tasks/{task_id}` | Service bearer token |
| GET | `/filetrans-results/{task_id}` | Expiring signature for exactly one artifact; no service token |

## Enable explicitly

Set `SONOVECT_COMPAT_MODEL` to one stable public model ID,
`SONOVECT_COMPAT_PUBLIC_URL` to the service HTTPS origin (without `/api/v1`),
`SONOVECT_COMPAT_INPUT_HOSTS` to comma-separated exact input hosts, and
`SONOVECT_COMPAT_SIGNING_KEY_FILE` to a dedicated persistent key file. Unconfigured
compatible routes return 503. Authentication and native jobs still work normally.

The signing file must contain 32–4096 bytes, be readable by the service identity,
have mode 0600 or stricter and not be a symlink. Create it once with a secure
random generator; retain it across restarts. It is independent of the service
bearer token. A new key revokes previously issued links.

`deploy/compose.filetrans.yml` is an optional overlay for a complete base recipe.
Supply `SONOVECT_COMPAT_SIGNING_KEY_HOST_FILE` for the existing restricted host
file, then combine `-f deploy/compose.qwen.yml -f deploy/compose.filetrans.yml`
(or the selected CPU/distributed/external-provider base). The file must be
readable by container UID 10001; Compose file secrets do not portably change host
ownership. The overlay passes the same compatibility settings to API and worker.
An HTTPS reverse proxy must route all four paths, avoid caching results and avoid
logging signed input bodies or result query strings. No public listener or model
download is created by enabling these settings.

The API image disables default Uvicorn access logs, which would include signed
query strings. Keep that behavior when overriding the container command.

## Request and result

```json
{
  "model": "operator-selected-model-id",
  "input": {"file_urls": ["https://approved-input.example/audio?signature=..."]},
  "parameters": {
    "language_hints": ["Chinese"],
    "diarization_enabled": true,
    "vocabulary": {"example term": 4}
  }
}
```

There is exactly one file, at most one language hint and at most 200 vocabulary
entries (1–80 characters, integer weights 1–5). Weights order model hints; they
are not a guarantee of relative influence. `vocabulary_id`, arbitrary model
selection and unknown parameters are rejected. Mono input is recommended;
clients must obtain their existing channel-mix consent before preparing mono
input. Sonovect's media limits and track selection rules still apply.

Submission returns 202 with `output.task_id` and `output.task_status`; an exact
idempotent repeat returns 200 with the same task. Poll statuses are `PENDING`,
`RUNNING`, `SUCCEEDED`, `FAILED` and `CANCELED`. A successful task contains
`output.results[].transcription_url`. Downloaded JSON contains
`transcripts[].sentences[]`, with `text`, optional `begin_time`, `end_time`,
`speaker_id` and real `words[]` text/time evidence. All times are milliseconds.
Unaligned nonempty text remains readable with absent timing. Empty speech fails
with `ASR_RESPONSE_HAVE_NO_WORDS`. Timing and speakers are never synthesized.
Model discovery declares capabilities; availability does not establish quality.

## Input security and recovery

Only HTTPS on port 443 is accepted. Exact configured hosts, all resolved public
IP addresses and the pinned connection address are checked. Redirects and private
network targets are refused; credentials are never forwarded to input hosts.
Downloads enforce size, free-space and time limits, then atomically retain a
digest-checked input. Signed input URLs stay in private task state.

Optional `X-Input-SHA256` binds the prepared recognition file. Combined with
`Idempotency-Key`, it allows a renewed signed URL to identify the original input;
without a digest, the complete input URL participates in request identity. A
changed input/options/model/vocabulary under the same key returns 409. Download
digest mismatch fails before inference. Each admitted task freezes the served
engine models/revisions and options; a mismatched worker fails explicitly.

Downloaded input survives an interrupted worker. Published result bytes survive
service restart and are not replaced by native retry; explicit reprocessing needs
a new submission/key. A lost response or failed download should first recover
the original task. Result links expire after `SONOVECT_COMPAT_LINK_SECONDS`
(default 3600), bounded by result retention; polling renews a link to the same
bytes while retained. After task retention, polling returns 410. A missing or
expired signed artifact cannot cause inference. No unknown task is auto-resubmitted.

`SONOVECT_COMPAT_DOWNLOAD_TIMEOUT` defaults to 300 seconds.
`SONOVECT_COMPAT_MAX_QUEUED` defaults to 32 queued/running compatible tasks;
capacity failure returns 409. Compatibility columns are added to the native
database; native task IDs/results remain unchanged. Upgrade API, worker and
bundled provider metadata together. Before rollback, stop new compatible
admissions and drain their tasks. Namespaced states prevent old workers from
claiming URL-backed tasks, but old software cannot serve their compatible API.
