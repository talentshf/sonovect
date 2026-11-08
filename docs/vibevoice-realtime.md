# VibeVoice file recognition and optional live transcription

These independent, opt-in adapters are included in v0.3.0. Model assets and
isolated GPU runtimes are prepared separately. The existing file route and its
durable task/recovery contract remain the default. Source-level support does
not establish GPU capacity, recognition quality, or a production release.

## VibeVoice file jobs

Sonovect speaks the [official VibeVoice vLLM protocol](https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-vllm-asr.md),
using `/v1/chat/completions` with inline audio, context hints and the structured
`Start time`, `End time`, `Speaker ID`, `Content` output. Use a private,
operator-managed endpoint root (without `/v1`), served model name `vibevoice`,
and the selected model revision `d0c9efdb8d614685062c04425d91e01b6f37d944`.
Keep the model endpoint private. For a key-authenticated upstream, set
`SONOVECT_PROVIDER_TOKEN_FILE` to its existing operator-managed secret file
(and mount that file read-only in both core containers). Sonovect itself keeps
its normal bearer authentication. Do not put credentials into URLs.

```sh
sonovect setup --route vibevoice --write deploy/.env.vibevoice
# Add SONOVECT_PROVIDER_URL=<private endpoint root> to the private configuration.
# Pass --env-file to Compose for variable interpolation as well as service env.
SONOVECT_ENV_FILE=.env.vibevoice docker compose --env-file deploy/.env.vibevoice -f deploy/compose.vibevoice.yml config --quiet
```

Build matching candidate core/media-worker images before starting this recipe;
set `SONOVECT_IMAGE` and `SONOVECT_WORKER_IMAGE` to those reviewed images.
The existing v0.2.0 images do not contain this adapter.
The recipe has two Sonovect containers **plus the external GPU model service**;
setup's zero download count applies only to local model assets, not to upstream
weights. The original BF16 weights are approximately 17.35 GB (16.2 GiB).

Our default admission limit is **900 seconds**, one model request per source.
Longer inputs fail during media decoding with `media_duration_exceeded`
(or `vibevoice_duration_limit_exceeded` at the adapter guard); they are not
silently chopped into independent speaker namespaces. Increase the limit only
after capacity tests on the actual GPU. A 24 GiB card is a short-input test
target, not a guarantee of one-hour processing. 32 GiB gives more room; for
long recordings/concurrency, evaluate 48/80 GiB class GPUs. These are planning
budgets, not measured requirements or a performance commitment. Attention
implementation, prompt/output length and concurrency change peak memory.
See the [upstream consumer-GPU report](https://github.com/microsoft/VibeVoice/issues/238)
and [duration/memory discussion](https://github.com/microsoft/VibeVoice/issues/367);
issue comments are user measurements, not a Microsoft hardware guarantee.

Outputs use the existing queue, result, subtitle and export APIs. Seconds are
converted to integer milliseconds, speaker labels become recording-local
anonymous IDs, and no word timings are invented from sentence intervals.
Truncated output, invalid JSON and out-of-range timestamps fail explicitly.
Repeated result reads do not repeat inference. The selected revision in task
identity is operator configuration; `/v1/models` confirms the served name only.
Verify the actual upstream revision separately before changing admission.

Optional environment/emotion/measurement stages are not yet supported on this
route and are rejected, rather than silently skipped. Use separate Compose
project/storage and an explicit consumer connection. Do not mix Qwen and
VibeVoice workers on one task queue or change Sayflit's default connection.

## Qwen realtime service

The existing file worker uses Transformers 5 and `-hf` weights. Qwen's official
`qwen-asr==0.0.6` streaming API requires vLLM 0.14.0 and Transformers 4.57.6.
This incompatibility is why the optional live runtime must be a **separate
GPU process/environment**, not a dependency downgrade in the deployed worker.
Use a locally prepared, exact-revision SDK-format `Qwen/Qwen3-ASR-1.7B`
directory; the file worker's pinned `-hf` directory is not interchangeable.
Reuse compatible shared runtimes/model caches when present. Otherwise prepare
this isolated runtime under the deployment's existing model/cache policy.
The dependency list is in `providers/realtime/requirements.txt`; install the
same selected Sonovect package/core dependencies into that environment and run
`python -m pip check`. This runtime is not included in the existing images and
must undergo its own dependency/image and GPU qualification before production.

Set `SONOVECT_TOKEN_FILE` through the existing native secret mechanism. Set
`SONOVECT_REALTIME_ENABLED=true`, `SONOVECT_REALTIME_MODEL_PATH=<local SDK model
directory>`, and optionally `SONOVECT_REALTIME_GPU_MEMORY_UTILIZATION=0.35`.
Then, from that GPU runtime:

```sh
uvicorn sonovect.realtime:create_realtime_app --factory --host 127.0.0.1 --port 8097 --workers 1 --ws-max-size 64000 --no-server-header
```

Use one process only: the concurrency guard is process-local. The standalone
service exposes `/health`, authenticated `/v1/capabilities`, and `/v1/realtime`; it does not create file queues.
Health is liveness plus a model-loaded flag, not recognition readiness. Models
load on the first authorized session. A startup/GPU probe and a real stream
must pass before exposing it to clients. The main API also registers the route
and advertises it only if explicitly enabled in that process. For the separate
service, configure the client URL to that service; main API discovery does not
pretend it owns an external live service.

Do not run this runtime and VibeVoice simultaneously on a 24 GiB card. Its
vLLM budget is reserved on model loading, not automatically released between
sessions. Stop/qualify the selected GPU service through normal deployment
controls before sharing its device; no automatic stop/unload is performed.

### Client

Install the optional `stream-client` extra in the client environment. Set its
`SONOVECT_URL` to the realtime service and use existing token/token-file auth.

```sh
sonovect stream mono-16khz-pcm16.wav --language Chinese --hotword Sonovect
# A microphone/recorder can pipe raw mono 16kHz little-endian signed PCM16:
sonovect stream --stdin --language Chinese
```

Output is NDJSON (one JSON object per line), flushed as audio is processed.
The WAV command is a streaming protocol check; it does not open a microphone.
`--stdin` accepts a live capture application's PCM stream. No OS audio
permissions or recording device are selected automatically. Keep the original
recording in the capture application if later alignment/diarization is needed.

### WebSocket contract: `sonovect.realtime/v1`

1. Connect to `/v1/realtime` with `Authorization: Bearer ...`. Query-string
   tokens are not accepted; direct browser access with a long-lived service
   token is not provided.
2. Send `{"type":"start","sample_rate":16000,"encoding":"pcm_s16le",
   "language":"Chinese","hotwords":["Sonovect"]}`. Wait for `started`.
3. Send binary PCM16 mono frames, at most 64000 bytes (2 seconds), an even,
   nonzero number of bytes. Wait for each `partial` before sending the next;
   this provides bounded backpressure rather than an unbounded input queue.
4. Each `partial.text` **replaces the entire preceding draft**. Do not append
   it: upstream may revise earlier words. `sequence` increases within one
   `session_id`. `received_audio_ms` measures received samples and is **not**
   an alignment timestamp.
5. Send exactly `{"type":"finish"}` to flush the tail, then receive `final`.
   Only `final` is a completed live transcript. An `error` is terminal; retain
   the last draft as incomplete on the client. Error responses do not include
   provider exception text, tokens or audio.

Default limits: 1 active session/process, 300 seconds of audio, 30 seconds idle,
2 seconds per frame. A second caller receives `realtime_busy`. Disconnect
abandons the session, does not call finish/reconnect/submit a file job, and
never releases an in-flight model slot until that call has actually ended.
Sessions are transient: the client owns draft/final persistence and must not
silently resubmit after connection loss. Existing file-job recovery is a
different contract. Qwen's SDK re-feeds accumulated audio with prefix rollback;
cost may grow with duration. We do not claim constant latency or online KV
caching. The Qwen route supplies neither live timestamps, speakers nor optional acoustic analysis. No Sayflit UI is added. For the separate VibeVoice 1.5B streaming backend, see below.

## Validation boundaries

Unit/contract tests use synthetic PCM and a deterministic injected engine or
HTTP model fixture. They cover real pre-finish protocol output, draft
replacement, tail flushing, auth, bounds, disconnects and file-job reuse.
They do **not** prove actual recognition, GPU peak usage, cold start, full
duration, concurrent consumer performance, image safety or deployment.

## VibeVoice Streaming 1.5B

This optional live route uses `microsoft/VibeVoice-ASR-Streaming-1.5B` at
revision `4262d23d8a539a6530cf64fbd0b1751ef9a30853`. Its complete required
asset set is 5,644,393,692 bytes (weights approximately 5.63 GB). The catalog
pins every file's size and digest. It is a different checkpoint/runtime from
the original offline VibeVoice backend above; do not interchange their paths.

Keep this route as an **on-demand alternative** to the default Qwen file
service. The adapter and recipe ship in v0.3.0; this runtime is not part of the
default deployment and no prebuilt realtime image is distributed.
The isolated container has `restart: 'no'`; launch it in the foreground and
remove it on exit. The model remains loaded between sessions in that process,
so stop the process when finished to release its GPU allocations.

```sh
sonovect setup --route vibevoice-1.5b --write deploy/.env.vibevoice-15
sonovect models prepare vibevoice-stream-1.5b --cache <operator-owned-huggingface-cache>
```

Use the native upstream streaming methods from the exact runtime commit in
`providers/realtime/requirements.vibevoice.txt`. Its Transformers <5 constraint
also requires an isolated runtime, not a downgrade of the deployed file worker.
Compatible existing Torch/CUDA and model/cache storage can be reused. Set
`SONOVECT_REALTIME_IMAGE` to an image qualified with this Sonovect source and
that runtime before using `deploy/compose.realtime.vibevoice.yml`. The recipe
runs one process/container without a file queue and mounts prepared models
read-only. Set `SONOVECT_MODELS_DIR` to the parent containing `huggingface/`,
with the snapshot path produced by the generated configuration. Missing or
modified checkpoint files fail verification before model loading. Normal
serving is offline. Core/client installation does not install the GPU SDK.

After selecting a qualified image and preparing the private configuration,
model assets and existing authentication, start only this service:

```sh
SONOVECT_ENV_FILE=.env.vibevoice-15 docker compose --env-file deploy/.env.vibevoice-15 -f deploy/compose.realtime.vibevoice.yml run --rm --service-ports --name sonovect-vibevoice-on-demand realtime
```

Use Ctrl+C when finished. From a separate terminal, run
`docker stop sonovect-vibevoice-on-demand`; verify that the one-off container has
exited before reallocating GPU capacity. Do not add this recipe to the default
file-service startup. Configuration generation and model preparation do not
start a service or switch an existing consumer.

For source-based serving, select `SONOVECT_REALTIME_BACKEND=vibevoice-1.5b`,
set the local snapshot in `SONOVECT_REALTIME_MODEL_PATH`, enable realtime and
reuse the same `uvicorn ...create_realtime_app` command and CLI shown above.
`SONOVECT_REALTIME_DEVICE` supports `cuda:0` (default, BF16) and `cpu` (FP32,
functional use only). The allocator budget is the existing
`SONOVECT_REALTIME_GPU_MEMORY_UTILIZATION` (default 0.35); free memory must
cover that budget plus 1 GiB before loading. This is a PyTorch allocator bound,
not a GPU-wide reservation or a claim about latency/capacity.

The public PCM contract stays at 16 kHz. One stateful SoXR resampler/session
converts it continuously to 24 kHz, including filter-tail flush. The native
model uses 22 x 3200 samples (2.933 s) plus 4 x 3200 samples (0.533 s) of
lookahead. Only the chunk advance is consumed; lookahead is retained for the
next window. The final real audio interval is padded when necessary, without
an extra inference on already-consumed lookahead. Native model KV state stays
within one authorized session. Default maximum duration is 300 s, with a hard
configuration ceiling of 480 s matching the released checkpoint scope.

`partial.text` / `final.text` retain the full native model text, including its
speaker labels. The optional `speaker_segments` list parses only emitted
`Speaker N:` labels into session-local anonymous integer IDs and original
segment text. Without a label, no identity is invented. These segments have
**no timestamps**: sample counts and model-window boundaries are not sentence
or word alignments. The same CLI accepts WAV and live PCM stdin with no model
selection on the client. Discovery reports the selected backend and speakers.

`scripts/qualify_vibevoice_stream.py` exercises the actual model through the
native service and CLI on two public Qwen sample recordings, and records GPU
allocator peaks and native speaker text. Run it only in the isolated trial
runtime with a new output directory. A completion receipt prevents repeating
finished trials. Its short samples do not establish Chinese meeting quality,
speaker accuracy, eight-minute stability, cold/warm distributions or
production-image acceptance.

An isolated RTX3090 / 24 GiB check on 2026-11-09 passed through the real model,
service and CLI. A 15.051 s English sample produced drafts before finalization;
the process peaked at 5004.9 MiB allocated and 5262 MiB reserved (5.14 GiB) in
the PyTorch allocator. This excludes other GPU allocations. A reused 4.204 s
Chinese case has no retained timing/memory measurements; its final text began
with “山治” where the [official sample reference](https://github.com/QwenLM/Qwen3-ASR/blob/main/examples/example_qwen3_forced_aligner.py)
has “甚至”. These brief checks establish functional integration, not a reason
to replace Qwen as the default. They are not microphone latency, long-session,
multi-speaker accuracy or production-image acceptance results.

For compilerless slim images on PyTorch 2.14, the recipe sets `TORCH_DISABLE_NATIVE_JIT=1`, the native supported fallback, before importing Torch. This avoids runtime compiler requirements without changing framework source. Images with a compiler can override it and qualify their own performance. Qualification preserves original public audio, converts other PCM rates/widths with FFmpeg, and reuses completed per-case events after a later case fails. Reused cases have no invented timing or memory measurements.
