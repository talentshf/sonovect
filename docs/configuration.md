# Configuration and model selection

Sonovect v0.1.0. Deployment selects components; jobs select execution. Jobs default to speech only. Setup writes a new mode-0600 configuration with a random token, never prints the token, and refuses overwrites.

## Recommended choices

| Need | Selection | Tradeoff |
| --- | --- | --- |
| Chinese CPU start | `--route cpu --sound none --voice none` | Paraformer v2.0.4, FSMN, punctuation, optional per-job CAM++ |
| Multilingual GPU | `--route qwen --speech 1.7b` | Recommended Qwen, fixed aligner, CAM++, FireRed VAD |
| Smaller speech model | `--speech 0.6b` | Experimental memory/quality tradeoff |
| Events | `--sound ast` (setup default) | Independent CPU AST; jobs opt in; no MOSS execution |
| Experimental emotions | `--voice emotion2vec` | CPU model, about1.12GB weights; Chinese quality unqualified |
| Open vocal descriptions | `--voice 4b` or `--voice 8b` | Optional GPU MOSS; larger capacity does not guarantee better emotion accuracy |
| Pitch/energy | `--measurements` | Independent weight-free CPU service, off by default |

CPU supports `--native-revision v2.0.4|v2.0.9`; the latter is a configuration variant, not new trained weights. Qwen supports `--vad firered|fsmn`. `--sound none|ast` and `--voice none|emotion2vec|4b|8b` are independent. One vocal backend is selected per deployment. No vocal choice implicitly enables measurements.

## Prepare and verify

```sh
sonovect setup --route cpu --sound ast --voice none --measurements --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml --plan
python scripts/prepare_deployment.py --compose deploy/compose.yml --check-hardware
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
python scripts/prepare_deployment.py --compose deploy/compose.yml --verify-only --smoke-audio sample.wav
```

For Qwen select `--route qwen` and `deploy/compose.qwen.yml`. Setup `--interactive` prompts for choices; `--write` refuses overwrite. Preparation accepts `--env-file`, existing Docker `--context`, `--plan`, `--verify-only`, `--check-hardware`, `--smoke-audio`, `--smoke-language`. Plans do not download; verification never writes caches or uses the network. Hardware checks verify selected-container access/capacity, not inference accuracy.

`sonovect models list` shows pinned assets; `models prepare MODEL... --cache DIRECTORY` prepares only selected identities; `models verify MODEL...` checks existing bytes offline. Missing, corrupt or mismatched files fail explicitly. Normal inference is offline after preparation. Component terms are informational; there is no acknowledgement flag. No weights are bundled.

## Jobs and outputs

Strict booleans `analyze_sound`, `analyze_voice`, `measure_voice` default false and are independent. There is one analysis schema. `speakers` defaults true; `language` is a model-specific hint; `hotwords` holds up to200 strings of1–80 characters; `audio_track` defaults0 and selects an audio stream, not a channel/speaker. HTTP, CLI and MCP share this contract; unknown fields and string booleans fail.

CLI controls: `--language`, `--no-speakers`, `--analyze-sound`, `--analyze-voice`, `--measure-voice` / `--no-measure-voice`, repeated `--hotword`, `--audio-track`, `--idempotency-key`, `--wait`. `sonovect wait JOB --timeout SECONDS` waits on the same job. `status`, `cancel`, `retry`, `analysis`, `export` operate on that ID. `result --format json|text|srt` reads one recognition; SRT requires one successful source with sentence timing. Export validates hashes and requires a new directory. See [usage](usage.md) and [results](results.md).

## Current generated defaults and connections

Setup defaults to `--route qwen --speech 1.7b --vad firered --sound ast --voice none --no-measurements --layout compact`: 3 installed containers, speech-only jobs. The following table gives deployment connections. The complete resource table below labels standalone process fallbacks separately; do not mix them into another recipe.

| Connection/control | compact | distributed |
| --- | --- | --- |
| `SONOVECT_PROVIDER_URL` (Qwen) | `http://worker:8080` | `http://speech-provider:8080` |
| `SEGMENTATION_URL` / `QWEN_URL` | `http://127.0.0.1:8082` / `http://127.0.0.1:8081` | `http://speech-segmentation:8082` / `http://speech-asr:8081` |
| `SONOVECT_SOUND_URL` / `EVENTS_URL` | `http://analysis:8084` | `http://speech-events:8084` |
| `SONOVECT_VOICE_URL` / `VOICE_URL` (emotion2vec) | `http://analysis:8085` | `http://speech-vocal:8085` |
| `SONOVECT_VOICE_URL` / `VOICE_URL` (MOSS) | `http://speech-sound:8083` | `http://speech-sound:8083` |
| `SONOVECT_MEASUREMENTS_URL` / `MEASUREMENTS_URL` | `http://analysis:8086` | `http://speech-measurements:8086` |
| `COMPOSE_PROFILES` (AST / CPU vocal / measurements / MOSS) | `analysis` / `analysis` / `analysis` / `voice` | `events` / `vocal-cpu` / `measurements` / `voice` |

## Compact and distributed deployment

`--layout compact|distributed` defaults to `compact`. Both CPU and Qwen use2base containers; any AST/emotion2vec/measurement combination adds1CPU analysis container; selected MOSS adds1independent GPU container. Setup returns `layout`, `compose_file`, `container_count`, exact model identities and download size. Use the generated recipe and profiles together. All job options and result fields are identical across layouts.

| Control | Default | Effect |
| --- | --- | --- |
| `SONOVECT_LAYOUT` | compact | Discovery metadata: compact, distributed or external; choose matching recipe |
| `SONOVECT_ANALYSIS_TARGET` | analysis-worker | Full optional CPU analysis build target; setup uses analysis-measurements for numeric-only selection |
| `SONOVECT_ANALYSIS_IMAGE` | sonovect-analysis | Distinct numeric-only image sonovect-analysis-measurements avoids model frameworks |
| `ANALYSIS_CPU_LIMIT`, `ANALYSIS_MEMORY_LIMIT` | 2, 6g | Shared CPU/memory ceiling of selected compact analysis processes; thread controls remain per module |
| `SEGMENTATION_CACHE`, `SEGMENTATION_HF_HOME` | /models/segmentation, /models/segmentation/huggingface | Qwen helper's ModelScope/Hugging Face cache; independent of ASR cache |
| `QWEN_HF_HOME` | /models/qwen/huggingface | Qwen ASR/aligner cache in compact speech worker |

Compact AST, CPU vocal and measurements URLs use `http://analysis:8084`, `http://analysis:8085`, `http://analysis:8086`; MOSS stays `http://speech-sound:8083`. Compact API uses `http://worker:8080`; its speech worker uses loopback coordinator, segmentation8082and ASR8081. `COMPOSE_PROFILES` is empty for speech only, `analysis` for CPU extras, `voice` for MOSS alone or `analysis,voice` for both. Advanced `--layout distributed` retains events/vocal-cpu/measurements/voice profiles and the standalone defaults in the tables above. `MEASUREMENTS_CPU_LIMIT`/`MEASUREMENTS_MEMORY_LIMIT` apply only to the distributed recipe; compact uses the shared analysis ceilings. Model roots remain independently configurable. Disabled processes never start; selected weights remain lazy. Preparation downloads only the selected catalog entries, and normal runtime remains offline.

`--no-measurements` explicitly disables deployment measurements, matching the default; `--measurements` enables them. Neither changes the independent per-job `measure_voice` flag.

## Complete resource controls

Allocator budgets do not equal total process VRAM. Reserve capacity for concurrent consumers. Longer timeouts do not improve speed. Thresholds, segmentation and windows change quality/cost; compare representative material. Numeric threads/windows/limits are independent of emotion windows. No usable speech yields no invented numbers.

| Control | Standalone fallback / explicit recipe value | Behavior / adjustment |
| --- | --- | --- |
| `SONOVECT_TOKEN` / `SONOVECT_TOKEN_FILE` | Required, mutually exclusive | Explicit token or a restricted file containing only the token; not an entire `.env` file |
| `SONOVECT_URL` | http://127.0.0.1:8096 | Client endpoint; clients do not implicitly load `.env` |
| `SONOVECT_MCP_INPUT_ROOT` | Unset, submissions disabled | Explicit readable input directory; resolved symlinks must remain inside it |
| `SONOVECT_PROJECT`, `SONOVECT_VERSION`, `SONOVECT_REVISION` | sonovect, current version, uncommitted | Compose name and image provenance; retain accepted image digests |
| `SONOVECT_BIND`, `SONOVECT_PORT` | 127.0.0.1, 8096 | Public API binding; preflight port ownership before changes |
| `SONOVECT_DATA_DIR` | ./data/jobs; container /data | Writable durable queue/input directory |
| `SONOVECT_BACKEND` | funasr | funasr or speech, selected by deployment |
| `SONOVECT_MODEL`, `SONOVECT_MODEL_REVISION` | paraformer-zh, v2.0.4 | Catalogued native combination; v2.0.9 is opt-in experimental configuration |
| `SONOVECT_DEVICE` | cpu | Native model device; changing this does not install GPU support |
| `SONOVECT_PROVIDER_URL` | http://speech-provider:8080 | Compatible private coordinator |
| `SONOVECT_SOUND_ENABLED`, `SONOVECT_SOUND_URL` | standalone core true (recipes false), empty | AST capability and native AST service URL; setup enables it for ast |
| `SONOVECT_PROVIDER_TIMEOUT` | 7200 s | Positive upstream timeout; increasing it does not improve speed |
| `SONOVECT_MAX_UPLOAD_BYTES`, `SONOVECT_MAX_FILES` | 268435456, 16 | Positive aggregate upload/file limits; decoded memory is separate |
| `SONOVECT_MAX_MEDIA_SECONDS`, `SONOVECT_MEDIA_TIMEOUT` | 7200 s, 300 s | Positive per-source decoded duration and decode timeout |
| `SONOVECT_INPUT_TTL_HOURS`, `SONOVECT_RESULT_TTL_HOURS` | 24 h, 168 h | Positive retention from terminal state; retries need retained inputs |
| `SONOVECT_LEASE_SECONDS`, `SONOVECT_POLL_SECONDS` | 120 s, 0.1 s | Positive renewable task lease and idle polling interval |
| `SONOVECT_WORKER_STALE_SECONDS`, `SONOVECT_WORKER_HEALTH_FILE` | 45 s, /tmp/sonovect-worker.json | Heartbeat age and process identity file; unique file for each standalone worker |
| `SONOVECT_MODELS_OFFLINE` | 1 in generated/runtime recipes | Explicit preparation vs offline runtime; CPU maps to MODELSCOPE_OFFLINE |
| `SONOVECT_ENV_FILE`, `SONOVECT_PROCESSING_NETWORK` | .env, sonovect_default | External-provider recipe configuration and existing private network |
| `SONOVECT_IMAGE`, `SONOVECT_WORKER_IMAGE` | Current core/media images | External-provider image overrides |
| `MIN_TEXT_DENSITY_PER_SPEECH_SECOND` | `0.2` | Nonnegative text-density warning threshold. |
| `MOSS_TIMEOUT_SECONDS` | `3600` | Positive acoustic-stage timeout in seconds. |
| `MOSS_URL` | `http://moss-audio-worker:8083` | Private sound worker URL. |
| `QWEN_TIMEOUT_SECONDS` | `1800` | Positive ASR-stage timeout in seconds. |
| `QWEN_URL` | `http://qwen3-asr-worker:8081` | Private ASR worker URL. |
| `SEGMENTATION_TIMEOUT_SECONDS` | `600` | Positive segmentation timeout in seconds. |
| `SEGMENTATION_URL` | `http://speech-segmentation-worker:8082` | Private segmentation worker URL. |
| `SEGMENT_BOUNDARY_SILENCE_MS` | `700` | Nonnegative silence boundary in milliseconds. |
| `SEGMENT_HARD_MAX_MS` | `90000` | Positive hard limit for base speech regions; padding is added separately. |
| `SEGMENT_MERGE_GAP_MS` | `3000` | Nonnegative mergeable gap in milliseconds. |
| `SEGMENT_PADDING_MS` | `1000` | Nonnegative padding on each side, bounded by media edges. |
| `SEGMENT_TARGET_MS` | `30000` | Positive soft target for base ASR regions; no greater than the hard maximum. |
| `SOUND_ENABLED` | `false` | true/false (also 1/0, yes/no); configured capability must agree with core. |
| `FIRERED_VAD_ROOT` | (unset) | Optional explicit directory; required FireRed bytes are still checksum-verified. |
| `MIN_SPEAKER_PROFILE_DURATION_MS` | `5000` | Nonnegative minimum internal profile duration; no cross-recording identity database. |
| `MODELSCOPE_CACHE` | `/models` | SDK cache root. The native image uses /models/modelscope. |
| `SEGMENTATION_DEVICE` | `cpu` | Packaged segmentation is CPU-only; changing the value does not install CUDA. |
| `SPEAKER_FALLBACK_COUNT` | `2` | Positive conservative fallback cluster count, not a declared true speaker count. |
| `SPEAKER_FALLBACK_MIN_WINDOWS` | `20` | Positive minimum evidence windows before the low-cohesion fallback. |
| `SPEAKER_LOW_COHESION_COSINE` | `0.45` | Cosine threshold in [-1,1] for low-cohesion single-cluster fallback. |
| `SPEAKER_MERGE_THRESHOLD` | `0.78` | Cluster merging threshold in [0,1]; changing it can change speaker count. |
| `SPEAKER_MODEL` | `cam++` | Pinned CAM++ alias. |
| `VAD_BACKEND` | `fsmn` | firered or fsmn. Compose maps SONOVECT_VAD_BACKEND and defaults to firered. |
| `VAD_MODEL` | `fsmn-vad` | Pinned FSMN alias; unused when FireRed is selected. |
| `GPU_CAPACITY_WAIT_SECONDS` | `360` | Nonnegative admission wait; zero fails immediately. |
| `GPU_RESERVE_MIB` | `1024` | At least 512 MiB outside the allocator budget; account for shared consumers. |
| `QWEN_ALIGNER_MODEL` | `Qwen/Qwen3-ForcedAligner-0.6B-hf` | Fixed catalogued forced-aligner identifier. |
| `QWEN_ALIGNER_REVISION` | `c07281df297b9905d24a508279258cccf987a064` | Fixed paired aligner revision. |
| `QWEN_ASR_MODEL` | `Qwen/Qwen3-ASR-1.7B-hf` | Catalogued 1.7B or experimental 0.6B ASR identifier. |
| `QWEN_ASR_REVISION` | `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` | Fixed paired ASR revision. |
| `QWEN_ATTENTION_IMPLEMENTATION` | `auto` | auto, sdpa or eager. Other attention packages are not bundled. |
| `QWEN_DEFAULT_CONTEXT` | (empty) | Explicit deployment-wide term hint; do not embed personal/private vocabularies. |
| `QWEN_DEVICE` | `cuda:0` | Visible CUDA device for this role; CPU/custom placement needs independent qualification. |
| `QWEN_DTYPE` | `bfloat16` | bfloat16, float16 or float32. Precision changes need memory/quality qualification. |
| `QWEN_GPU_BUDGET_MIB` | `8192` | Positive PyTorch allocator cap in MiB, bounded by actual device capacity. |
| `QWEN_IDLE_UNLOAD_SECONDS` | `300` | Positive integer seconds for idle eviction; smaller values increase cold loads. |
| `QWEN_MAX_BATCH_AUDIO_SECONDS` | `60` | Positive batching target; an oversized single region is still processed alone. |
| `QWEN_MAX_BATCH_SIZE` | `1` | Integer ASR batch size in [1,4]; larger batches can exhaust memory. |
| `QWEN_MAX_NEW_TOKENS` | `2048` | Positive generation cap per ASR segment, not per entire recording. |
| `QWEN_MIN_FREE_GIB` | `6` | Nonnegative free-memory floor; the budget-plus-reserve floor also applies. |
| `QWEN_ROLLING_CONTEXT_CHARS` | `0` | Nonnegative prior-text context length; zero disables. Errors can propagate. |
| `MOSS_AUDIO_MODEL` | `OpenMOSS-Team/MOSS-Audio-4B-Instruct` | Catalogued 4B or experimental 8B identifier. |
| `MOSS_AUDIO_REVISION` | `6907a499dc0e87cc77c8ae0fe23fd0eb5476a02d` | Fixed paired sound revision. |
| `MOSS_DEBUG_RAW` | `false` | true/false; diagnostic output can contain media-derived content, off by default. |
| `MOSS_DEVICE` | `cuda:0` | Visible device for the sound role. |
| `MOSS_GPU_BUDGET_MIB` | `12288` | Positive allocator cap; 8B setup selects 19456 MiB. Not total-process memory. |
| `MOSS_IDLE_UNLOAD_SECONDS` | `300` | Positive integer seconds for idle eviction. |
| `MOSS_MAX_CHUNK_SECONDS` | `90` | Positive maximum acoustic window; longer windows need more memory. |
| `MOSS_MAX_NEW_TOKENS` | `768` | Positive generation cap per acoustic window; small values can truncate JSON. |
| `MOSS_MIN_FREE_GIB` | `10` | Nonnegative loading floor; cannot increase the allocator cap by itself. |
| `MOSS_MODEL_ROOT` | (unset) | Optional explicit snapshot directory; exact catalog file verification remains required. |
| `MOSS_STRUCTURED_RETRIES` | `2` | Nonnegative retries for invalid structured output. |
| `MOSS_UNLOAD_AFTER_REQUEST` | `true` | true/false; retained models are explicitly released before the next ASR stage. |
| `SONOVECT_VOICE_ENABLED` | false | Independent vocal capability; endpoint is in the deployment table |
| `SOUND_ENABLED` / `VOICE_ENABLED` | false / false | Matching coordinator capabilities |
| `EVENTS_URL` / `EVENTS_TIMEOUT_SECONDS` | `http://speech-events:8084` / 600 | Event-stage URL/positive timeout |
| `COMPOSE_PROFILES` | setup `analysis`; speech-only empty; MOSS adds `voice` | Install only selected services |
| `SOUND_EVENT_MODEL_ROOT` | unset | Explicit verified AST directory inside the container |
| `SOUND_EVENT_THRESHOLD` | 0.1 / [0,1] | Higher reduces weak tags and increases misses; not calibrated accuracy |
| `SOUND_EVENT_TOP_K` | 5 / integer1–10 | Tags per window; parent/child tags may repeat one sound |
| `SOUND_EVENT_WINDOW_SECONDS` | 10 / [1,10] seconds | Smaller improves temporal granularity at higher CPU cost, not exact onset |
| `SOUND_EVENT_THREADS` | 2 / integer1–32 | CPU compute threads, shared-host contention remains |
| `SONOVECT_MEASUREMENTS_ENABLED` | false | API/worker independent capability; must match provider |
| `SONOVECT_MEASUREMENTS_URL` | private service URL in generated configuration | Native worker endpoint |
| `MEASUREMENTS_ENABLED`, `MEASUREMENTS_URL` | false, `http://speech-measurements:8086` | Speech coordinator capability/endpoint |
| `MEASUREMENTS_TIMEOUT_SECONDS` | 600 | Coordinator numeric-stage deadline |
| `MEASUREMENT_THREADS` | 2 | CPU/Numba threads, 1–32 |
| `MEASUREMENT_WINDOW_SECONDS` | 10 | Measurement window, 1–30 seconds; independent of `VOCAL_WINDOW_SECONDS` |
| `MEASUREMENTS_CPU_LIMIT`, `MEASUREMENTS_MEMORY_LIMIT` | 2, 2g | Compose service resource ceilings |
| `SONOVECT_VOICE_BACKEND` / provider `VOICE_BACKEND` | `moss`; `moss` or `emotion2vec` | Deployment selection; setup keeps core and coordinator aligned |
| `SONOVECT_VOICE_URL` / provider `VOICE_URL` | MOSS `http://speech-sound:8083`; compact CPU `http://analysis:8085`; distributed CPU `http://speech-vocal:8085` | Private service endpoint; not a task-selected URL |
| `VOCAL_MODEL_ROOT` | unset | Optional fixed verified directory inside the CPU service |
| `HF_HUB_CACHE` | SDK default under `HF_HOME` | Existing native Hugging Face cache override, not another cache registry |
| `VOCAL_THREADS` | 2; integer 1–32 | Torch CPU threads; recipes reserve two CPUs |
| `VOCAL_WINDOW_SECONDS` | 10; 1–30 seconds | Nonoverlapping analysis windows; smaller increases overhead and changes context/quality |

[Deployment](deployment-options.md) · [Component sources](model-licenses.md) · [Security](../SECURITY.md)

`sonovect --version` reports the product version; `sonovect ready` checks readiness without loading models.

Preparation checks capacity before any download, hashes existing selected files offline, aggregates missing bytes per filesystem and reserves one largest missing file for staging plus 1 GiB. Complete caches need no additional download space; explicit model roots are verified first and are never downloaded again. `--verify-only` makes no writable-capacity demand. `--plan` prints a location-independent selection summary; `sonovect models plan MODEL... --cache DIRECTORY` inspects the current cache without writes. Concurrent external disk use can still change available space.

## Event windows and long recordings

AST filterbanks need at least one 25 ms frame. A shorter final fragment is zero-padded only for feature extraction; reported timestamps retain the actual media bounds in integer milliseconds. Sub-millisecond fragments with no representable interval produce no observation. A short tail no longer fails earlier valid windows; this does not establish accuracy on arbitrarily brief sounds.

CPU event processing grows with the number of windows. Set `EVENTS_TIMEOUT_SECONDS` and the overall processing deadline using measurements on the deployment hardware; smaller windows also increase computation. The [quality protocol](quality-protocol.md) defines the parameter comparison scope. Scores are not calibrated accuracy probabilities.

## Shared GPU loading and diagnostics

Qwen and MOSS verify the selected immutable model files before measuring free GPU memory immediately before model allocation. Hashing a large checkpoint can take tens of seconds; capacity observed before hashing can change while another service loads. The admission floor is the larger of the selected minimum-free setting and allocator budget plus reserve. The8B selection sets19456MiB allocator budget and20GiB minimum free; `GPU_CAPACITY_WAIT_SECONDS` bounds the wait after verification. A long wait changes cold-start latency, so measure it separately from warm inference.

The admission check reads current availability; independent processes can still allocate memory afterwards. Run ordinary benchmark/qualification workloads serially on the shared card, account for other consumers and retain their timing when deliberately testing contention. On a failed optional vocal stage, valid speech and sibling analyses remain available; retry the same job after capacity recovers. Increasing an allocator cap does not create physical memory.

MOSS logs the exception type and a formatted stack on runtime failure, and reports invalid JSON/vocal structure attempts by reason and character count. The native adapter logs the optional stage and upstream status. These diagnostics omit audio bytes and generated descriptions by default. `MOSS_DEBUG_RAW=true` explicitly enables raw model descriptions in the internal response; use it only with material appropriate for the operator's diagnostic storage. Traceback objects are detached before CUDA cleanup to release partially loaded models.

Transient SQLite writer contention is retried by the worker instead of stopping the selected runtime. Idle queue/status polling avoids unnecessary writer transactions; expiry and lease decisions are rechecked under the write lock. Busy retries wait at least100ms; normal idle polling keeps `SONOVECT_POLL_SECONDS`. Permanent storage errors still stop the worker. Input/result retention, cancellation and same-job retry keep their existing deadlines.

The Mandarin supplement does not qualify stable emotion recognition: the default FireRed/base path reaches 45% strict accuracy on 480 acted test clips and emits emotions on 14/100 natural non-speech controls. Keep `--voice none` as the dependable starting point and use independent measurements when needed. See [quality](quality.md) before enabling experiments; model size or shorter windows alone do not guarantee improvement.
