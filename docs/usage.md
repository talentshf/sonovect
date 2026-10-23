# Usage

Sonovect v0.1.0. Configure a service endpoint and one authentication method (`SONOVECT_TOKEN` or `SONOVECT_TOKEN_FILE`); the latter contains only the token. No client implicitly reads a deployment environment file. Query `sonovect capabilities` before requesting optional features.

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
