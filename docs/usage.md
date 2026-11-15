# Usage

Sonovect v0.3.0. Configure a service endpoint and one authentication method (`SONOVECT_TOKEN` or `SONOVECT_TOKEN_FILE`); the latter contains only the token. No client implicitly reads a deployment environment file. Query `sonovect capabilities` before requesting optional features.

| Option | Default | Meaning |
| --- | --- | --- |
| `language` | null | Model-dependent language hint |
| `speakers` | true | Anonymous recording-local speaker labels |
| `hotwords` | [] | Up to200 hints,1–80 characters each |
| `audio_track` | 0 | Zero-based audio-stream selection, applied to all sources |
| `analyze_sound` | false | Independent AST events |
| `analyze_voice` | false | Deployment-selected experimental emotion2vec/MOSS |
| `measure_voice` | false | Independent weight-free pitch/energy |

The three analysis switches never imply each other. All booleans are strict; unknown fields fail. A deployment selects one vocal backend; jobs cannot change it. Missing capability is rejected before admission. Video uses only its selected audio track; channels downmix to mono.

Qwen hotwords are vocabulary hints, not text to insert into a transcript. They
are labelled using the [documented vocabulary prompt](https://huggingface.co/docs/transformers/v5.20.2/model_doc/qwen3_asr#context--hotwords).
Qwen can nevertheless [copy context into its output](https://github.com/QwenLM/Qwen3-ASR/issues/186).
When a chunk copies adjacent vocabulary entries or a longer context span,
Sonovect decodes that same chunk once more without any context, then aligns the
accepted text. It does not delete matching words: a genuinely spoken list can
survive the second decode. Ordinary individual term matches need no recheck.
Rechecking uses the same model and task, with extra inference only for suspect
chunks; it is not a new submission or a reprocessing of old results. This guard
reduces context copying but does not guarantee correct recognition of every
term, particularly in weak or ambiguous speech. An unsuccessful recheck fails
the source instead of accepting the known suspect output.

```sh
sonovect submit clip.wav --no-speakers --wait
sonovect submit clip.mp4 --audio-track 0 --analyze-sound --measure-voice --wait
sonovect submit clip.wav --language English --hotword Sonovect --analyze-voice
sonovect wait JOB_ID --timeout 7200
sonovect status JOB_ID
sonovect result JOB_ID --format json
sonovect result JOB_ID --format text
sonovect result JOB_ID --format srt
sonovect analysis JOB_ID
sonovect export JOB_ID new-directory
sonovect cancel JOB_ID
sonovect retry JOB_ID
```

Submission returns a durable ID, not a transcript. Query the same ID while `queued`/`running`; terminal states are `succeeded|partial|failed|cancelled|expired`. Timeout does not justify resubmission. `--idempotency-key` prevents exact duplicate admission; different inputs/options with one key conflict. Retry explicitly reprocesses retained inputs and can use the current deployment; retrieval never reruns inference.

SRT requires one successful source and sentence timing. Multiple files have independent clocks. Export refuses an existing directory and verifies artifact hashes. Partial jobs retain successful results and explicit failed-source/stage details. Defaults are16files,256MiB aggregate and7200decoded seconds per file, with24hour input and168hour result retention. Limits and resource controls are in [configuration](configuration.md).

## General audio service (0.4)

Use the deployed model IDs from `/v1/models`. A single recording normally needs only `POST /v1/audio/transcriptions`; it defaults to no diarization, alignment, sound classification or measurements. OpenAI SDK clients can use `audio.transcriptions.create`, `audio.translations.create` (English target), and the audio-input subset of `chat.completions.create` (one user audio+question message, text output, no generation settings or streaming). Translation uses recognized speech plus the configured text model. Audio questions send actual normalized audio to a separately configured understanding model and are marked for review.

| User need | Standard connection | Native Agent/CLI option |
| --- | --- | --- |
| Get text quickly | OpenAI `/v1/audio/transcriptions` | `sonovect transcribe FILE` |
| Subtitles / locate words | OpenAI `srt`, `vtt`, `verbose_json` with `timestamp_granularities=["word"]` | `submit --timestamps word` |
| Who spoke | OpenAI `diarized_json`; Deepgram `diarize=true` | `submit --speakers` |
| Translate | OpenAI `/v1/audio/translations`, English only | `submit --translate-to LANGUAGE` |
| Sound labels | HF `InferenceClient.audio_classification`, model URL `/models/ast-audioset` | `submit --no-transcribe --classify-audio` |
| Ask about a sound | OpenAI audio `input_audio` Chat Completions, configured audio model | `submit --no-transcribe --audio-question QUESTION` |
| Align known text | No common vendor-neutral contract | `submit --no-transcribe --language zh --alignment-text TEXT` |
| Keep channels separate | Deepgram file `multichannel=true` | `submit --channel-mode independent` |
| Speech / speaker time ranges | Sonovect independent task options | `submit --no-transcribe --detect-speech` or `--speakers` |
| Pitch / relative energy | Sonovect measurement result | `submit --no-transcribe --measure-voice` |
| Long recordings | Sonovect jobs + SSE events / signed completion callback | `submit --wait` or `--callback-url URL` |
| Send live turns | OpenAI `/v1/realtime?intent=transcription`, manual or neural endpoints | `stream FILE` (24kHz mono PCM16) |
| Deepgram clients | `/v1/listen`, raw uploaded file; live PCM with optional neural endpointing; `interim_results=false` | Neural speech endpoints or explicit `Finalize` / `CloseStream` |
| FunASR clients | `/v1/funasr`, `mode=offline`, PCM8k/16k | Explicit end-of-speech turns, no online/2pass claim |
| Home Assistant | Optional Wyoming TCP listener, default10300 | One shared ASR owner, external endpoint detection |

Use Bearer authentication everywhere; Deepgram additionally accepts its standard `Token` header. The service does not alias vendor-specific model names to unrelated models. Unsupported options fail before admission. Deepgram confidence fields are absent because the selected ASR does not provide them. Native client waiting consumes completion SSE instead of a growing polling interval. A disconnected wait never causes a resubmission.

HF classification includes speech and all other AudioSet classes, unlike filtered environment-event analysis. Scores are duration-weighted means of raw per-window sigmoid scores (at most10 seconds per window); these are uncalibrated class scores, not probabilities that an event spans the recording. The result header names the aggregation. `--analyze-sound` instead requests filtered windowed environment events. Emotion/voice descriptions remain experimental. Sound answers are model descriptions, not precise event timestamps.

Independent channel mode handles up to8 channels. Each channel gets its own source key, transcript, original clock and channel index. Channels are not speaker identities. Readable subtitle cues use actual aligned word boundaries when available; supported source segment boundaries are the fallback. Translated subtitles retain source segment times and have no target-word timing.

For a local translation model sharing the speech GPU, set `SONOVECT_TRANSLATION_URL` to the speech coordinator `/translation/v1` and `TRANSLATION_BACKEND_URL` to the actual text service `/v1`. The coordinator serializes GPU work and confirms its own speech/sound models are released before translation. Independent external compute can use the direct standard upstream.
