<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/brand/butterfly-dark.svg"><img src="assets/brand/butterfly-color.svg" alt="Sonovect purple butterfly" width="240"></picture></p>
<p align="center"><strong>Sonovect · Sound, structured.</strong></p>

[中文](README.zh-CN.md) · [Configuration](docs/configuration.md) · [Deploy](deploy/README.md) · [Benchmarks](docs/quality.md) · [Agent setup](docs/agent-setup.md) · [Discussions](https://github.com/talentshf/sonovect/discussions) · [Contribute](CONTRIBUTING.md)

[![Checks](https://github.com/talentshf/sonovect/actions/workflows/checks.yml/badge.svg)](https://github.com/talentshf/sonovect/actions/workflows/checks.yml) · [Apache-2.0](LICENSE) · Python 3.12+ · [v0.1.0 release notes](docs/release-v0.1.0.md)

# Cloud-class speech recognition. Your own hardware.

**Sonovect v0.1.0 is a self-hosted ASR assembly platform for recordings and video soundtracks.** Receive transcripts, timestamps and optional anonymous speakers in FunASR-compatible JSON, plain text and SRT. Environmental sounds, experimental vocals and signal measurements are separate results. HTTP, CLI and MCP use the same durable job workflow.

Run on your CPU or NVIDIA GPU and control media, results and retention. Once model assets are prepared, recognition runs locally without a cloud ASR service. In our same-audio comparison, local Qwen1.7B matched the tested cloud services on English and made fewer character errors in the Mandarin meeting:

| Same audio, measured 2026-10-21; fewer errors is better | Local Qwen1.7B | Bailian Fun-ASR | Bailian Qwen3-ASR |
| --- | ---: | ---: | ---: |
| 39-minute Mandarin meeting, 8073 reference characters | **7.42% CER** | 8.40% | 7.78% |
| 12 English clips, 241 reference words | **0 word errors** | 1 word error | **0 word errors** |

All three received identical mono audio and the same scoring rules. Local hardware was an RTX3090 / 24GiB. These are reference results for the measured material; see [benchmarks](docs/quality.md) for configuration, non-speech behavior and reproduction. Events and experimental emotions are evaluated separately.

Select speech, CPU AST events, emotion2vec/MOSS vocals and weight-free pitch/energy independently. **Download only selected assets; run only requested stages.** Both vocal backends remain optional experiments. See [publication status](PUBLICATION.md) for distribution availability.

## Deploy in 2–3 containers

Both speech routes use **two base containers**: the job API/queue and the speech worker. Add **one CPU analysis container** for any combination of AST, emotion2vec and measurements. MOSS is a separate optional GPU container, bringing a full installation to four. Selecting only measurements uses a lightweight image without Torch, FunASR or emotion weights.

| Selection | Containers |
| --- | ---: |
| CPU or Qwen speech only | 2 |
| Speech + any CPU analysis combination | 3 |
| Speech + MOSS, without CPU analysis | 3 |
| Speech + CPU analysis + MOSS | 4 |

The default `--layout compact` keeps model processes isolated inside these units; only selected analysis processes start and weights load on request. `--layout distributed` retains independent service scaling. Setup prints the exact recipe, container count, model identities and download size before preparation.

## Inputs and outputs

| Input | Choices | Output |
| --- | --- | --- |
| WAV, FLAC, MP3, M4A/AAC, OGG/Opus, AIFF | Language/term hints, anonymous speakers | FunASR speech JSON, text, SRT |
| MP4, MOV, MKV, WebM, AVI | Select an audio track; no visual/frame analysis | Speech plus independent sound analysis |
| Speech, music and background sounds | Independent events, vocals and measurements | Separate `analysis.json`, stage status and provenance |

Content probing determines format; codec support depends on the media worker. Defaults: 16 files, 256 MiB aggregate upload, two decoded hours per source. Channels downmix to mono, not speaker identities. Missing timing or speaker evidence is omitted.

## Choose a route

| Need | Deployment selection | Job flag |
| --- | --- | --- |
| Chinese CPU start | `--route cpu --sound none --voice none` | Speech only |
| Multilingual GPU | `--route qwen --speech 1.7b` | Speech only |
| Events | `--sound ast` | `--analyze-sound` |
| CPU experimental emotions | `--voice emotion2vec` | `--analyze-voice` |
| GPU open vocal descriptions | `--voice 4b` / `--voice 8b` | `--analyze-voice` |
| Weight-free pitch/energy | `--measurements` | `--measure-voice` |

Setup defaults to Qwen 1.7B, compact deployment, AST, no vocals and no measurements; all three per-job analysis flags default false. One vocal backend is selected per deployment. AST never delegates event calculation to MOSS. Numeric measurements need no emotion weights. Qwen 0.6B, native configuration variants, VAD, thresholds and every parameter are in [configuration](docs/configuration.md).

## Quick start

Use Python 3.12+, Docker and Compose. From the source directory, start with the native CPU recipe:

```sh
python -m pip install '.[mcp]'
sonovect setup --route cpu --sound ast --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
```

Setup writes a random token to a new mode-0600 file. Configure the client's `SONOVECT_URL` and `SONOVECT_TOKEN_FILE` or token environment as in [agent setup](docs/agent-setup.md); the client does not automatically read `deploy/.env`. Qwen additionally requires supported NVIDIA runtime/driver capacity. See [deployment](deploy/README.md).

```sh
sonovect capabilities
sonovect submit clip.mp4 --analyze-sound --wait
sonovect status JOB_ID
sonovect result JOB_ID --format text
sonovect result JOB_ID --format srt
sonovect analysis JOB_ID
sonovect export JOB_ID new-result-directory
```

Queries and exports reuse existing results. Inputs default to 24 hours and results 7 days after terminal state, configurable. Successful speech and sibling stages survive optional failures. Cancellation, explicit retry and idempotency are documented in [usage](docs/usage.md). This is a file-job service, with no browser UI or live streaming endpoint.

## Speech stays separate

`/v1/jobs/{id}/result` returns a source list, for example:

```json
[{"key":"audio_0000","text":"Hello.","sentence_info":[{"text":"Hello.","start":100,"end":500,"spk":0}]}]
```

`/v1/jobs/{id}/analysis` uses one `audio-analysis-v1` contract with `events`, `emotions`, `voice`, `measurements`, stage states and model/algorithm identities. Sound tags never decorate transcript text. Timestamps are integer milliseconds from original media start. Measurements do not establish emotion, identity, health or calibrated physical loudness.

## Assistant integration

After deployment, follow [agent setup](docs/agent-setup.md) to install the client, register MCP and install the matching [Sonovect skill](skills/sonovect/SKILL.md). The skill guides feature choice, submission, waiting and result retrieval; it contains no models or credentials. This release provides a standard stdio MCP server and a portable skill package.

## Join in

Help make local ASR easier to run on more hardware. Share deployment experiences in [Discussions](https://github.com/talentshf/sonovect/discussions), report a reproducible problem in [Issues](https://github.com/talentshf/sonovect/issues/new/choose), or improve a guide, translation or integration. First-time contributors are welcome; [start with the contribution guide](CONTRIBUTING.md).

[Documentation](docs/README.md) · [Architecture](docs/architecture.md) · [Operations](docs/operations.md) · [Security](SECURITY.md) · [Component sources](docs/model-licenses.md) · [Contributing](CONTRIBUTING.md) · [Publication](PUBLICATION.md)
