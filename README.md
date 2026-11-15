<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/brand/butterfly-dark.svg"><img src="assets/brand/butterfly-color.svg" alt="Sonovect purple butterfly" width="240"></picture></p>
<p align="center"><strong>Sonovect · Sound, structured.</strong></p>

[中文](README.zh-CN.md) · [Connect an application](docs/connections.md) · [Deployment](deploy/README.md) · [Agent setup](docs/agent-setup.md) · [Measured quality](docs/quality.md)

[![Checks](https://github.com/talentshf/sonovect/actions/workflows/checks.yml/badge.svg)](https://github.com/talentshf/sonovect/actions/workflows/checks.yml) · [Apache-2.0](LICENSE) · Python 3.12+ · [0.4.1 release guide](docs/release-v0.4.1.md)

# Your speech processing service, connected your way

**Sonovect is a self-hosted service for transcription, translation into text and sound understanding.** Connect an application through a familiar API, ask an agent to process a recording, or submit files from the command line. Receive the text, subtitles, translation or separate sound analysis you requested.

Ordinary transcription keeps the path short: speaker features, forced alignment and optional sound analysis run only when requested. Qwen recognition stays loaded for 30 idle minutes by default. Heavy local translation or understanding work coordinates its own model handoff on a shared GPU.

Download [v0.4.1](https://github.com/talentshf/sonovect/releases/tag/v0.4.1), including the client, source and standalone agent skill. See [scope and limits](docs/release-v0.4.0.md) before choosing a deployment. No speech generation is included.

## Choose the result

| What you need | What Sonovect provides |
| --- | --- |
| A quick voice message | One-call transcription and automatic language detection |
| Long recordings or a batch of files | Durable jobs, event waiting, recoverable task IDs and explicit retry |
| Subtitles or precise timing | SRT/VTT, segment or word timing, supplied-text alignment |
| Conversations and separate channels | Recording-local anonymous speakers and independent channel transcription |
| A translation | English through the standard audio-translation API; other targets through job options; source text retained |
| Microphone input | Shared-model transcription sessions with manual or neural speech endpoints |
| Sound analysis | Independent speech activity, environment events, AudioSet class scores, pitch and energy |
| A question about a sound | Configured audio-input model answering in text; answers require review |

Emotion/vocal observations remain experimental. Availability follows the selected backend and models; [capability discovery](docs/api.md) reports actual options, language support and limits.

## Connect existing tools

| Client ecosystem | Entry point | Supported behavior |
| --- | --- | --- |
| OpenAI-compatible applications | `/v1/audio/transcriptions`, `/v1/audio/translations`, `/v1/chat/completions` | Files, subtitles, English translation, one-audio text question |
| OpenAI Realtime | `/v1/realtime?intent=transcription` | Committed-turn transcription; manual or neural endpoints |
| Deepgram clients | `/v1/listen` | Uploaded files and final-turn WebSockets; optional independent channels |
| FunASR clients | `/v1/funasr` | Offline PCM turns; no online/two-pass emulation |
| Home Assistant | Optional Wyoming TCP bridge | Native ASR protocol on a trusted local network |
| Hugging Face clients | `/models/ast-audioset` | AudioSet classification scores |
| Long-recording applications | Optional DashScope-compatible `/api/v1` | Controlled URL-backed asynchronous file jobs |
| Agents and automation | CLI, stdio MCP and the included skill | The same processing options, task state and artifacts |

These are documented protocol subsets, not calls to those vendors' cloud services. Inference uses the models and upstreams configured by the operator. See the [connection checklist](docs/connections.md) for addresses, authentication and restrictions.

## Start locally

Use Python 3.12+, Docker and Compose. In the source checkout, this CPU example needs no GPU:

```sh
python -m pip install '.[mcp]'
sonovect setup --route cpu --sound ast --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
```

Setup creates a protected configuration and random service token. Configure the client separately with `SONOVECT_URL` and `SONOVECT_TOKEN_FILE`; it does not read the deployment environment automatically. For Qwen GPU speech, choose `--route qwen` and the matching [deployment recipe](deploy/README.md). Translation, audio understanding and the optional bridges require their documented configuration and assets.

```sh
sonovect capabilities
sonovect transcribe voice.wav
sonovect submit meeting.mp4 --speakers --timestamps word --wait
sonovect submit recording.wav --translate-to en --wait
sonovect submit sound.wav --no-transcribe --classify-audio --wait
sonovect result JOB_ID --format srt
sonovect translation JOB_ID
sonovect export JOB_ID new-result-directory
```

Plain transcription is the default. Independent analysis can disable transcription entirely. File-stream output returns real completed chunks; realtime output returns text after each committed speech turn, without an online word-by-word draft. Successful stages and source text survive auxiliary failures. Signed completion callbacks require an operator-configured receiver and allowlist; they do not automatically wake an agent.

## Models and deployment

Qwen3-ASR is the default speech route; native FunASR CPU speech and separately provisioned VibeVoice/Qwen experimental realtime runtimes remain optional. Forced alignment and speaker features load on demand. AST handles sound classification; emotion2vec or MOSS supply optional experimental vocal observations. A pinned, text-only Qwen2.5-Omni Thinker is available in the compact Qwen worker; operators can also configure compatible audio-input/text services.

Typical speech deployments use two base containers and one optional CPU analysis container. A Wyoming bridge adds one small container without another recognition model. Selected weights download separately at fixed revisions; source and packages contain no model weights. [Configuration](docs/configuration.md) lists every option and [component sources](docs/model-licenses.md) records upstream identities.

## Evidence and participation

[Quality results](docs/quality.md) retain their original corpus, date and configuration. They do not establish translation, realtime or sound-question accuracy. Audio understanding can misinterpret speech or guess a sound source; numeric measurements do not establish identity, health or emotional truth.

Share a deployment in [Discussions](https://github.com/talentshf/sonovect/discussions), report a reproducible problem in [Issues](https://github.com/talentshf/sonovect/issues/new/choose), or [contribute](CONTRIBUTING.md). The README is the product introduction; no separate site or account is required.

[Documentation](docs/README.md) · [Architecture](docs/architecture.md) · [Operations](docs/operations.md) · [Security](SECURITY.md) · [Publication](PUBLICATION.md)
