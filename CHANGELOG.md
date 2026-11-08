# Changelog

## Unreleased

## 0.3.0 — 2026-11-09

- Retain the newly observed low-severity GCC parser finding as an explicit residual service limitation, bound to the exact library and observed restrictions; do not claim a library fix or decoder unreachability.

- Add pinned VibeVoice Streaming 1.5B assets and a native realtime route with stateful 16kHz-to-24kHz resampling, checkpoint-specific chunk/lookahead buffering, tail flushing and session-local speaker segments.
- Document VibeVoice 1.5B as an on-demand alternative, disable automatic container restart and retain the default Qwen file route.
- Add an opt-in VibeVoice vLLM file backend with bounded duration, recording-local speakers and sentence-only timing; preserve the durable job and compatible result flows.
- Add authenticated Qwen live PCM sessions and `sonovect stream` for WAV or raw PCM stdin. The isolated optional upstream SDK runtime supplies revisable text and a final tail flush; timestamps, speakers, session resumption and Sayflit UI are not provided. No model/GPU/deployment qualification is implied.
- Declare the WebSocket transport in the test and isolated realtime runtimes, so clean installations can exercise the service and CLI without relying on host packages.

## 0.2.0 — 2026-11-07

- Rebuild fixed SQLite 3.54.1 and Debian security zlib sources; retain CRC fixes, remove unused APT download code and disable build-time APT retries. Refresh exact-source advisory decisions and retain the remaining explicit service boundaries.

- Add an opt-in single-file DashScope-compatible asynchronous interface with controlled HTTPS inputs, durable engine-bound tasks, signed results and preserved word evidence. Native speech and analysis results remain separate.
- Add a deployment overlay and report pinned segmentation model revisions for compatible admission. No runtime upgrade or public network route is implied by these source changes.

## 0.1.1 — 2026-11-01

- Update hydra-core to 1.3.8 for the current upstream advisory and qualify the new gettext locale limitation with fixed C locale and checked image evidence.

- Add safe readiness failure codes and authenticated component diagnostics, including GPU device access failures, worker presence and optional-service warnings.
- Preserve expected readiness failures in CLI, MCP and container checks; support older servers and retain existing 200/503 semantics.
- Bound and parallelize provider discovery, cap responses, distinguish GPU probe failures and reap timed-out probe processes. Model inference and job recovery behavior are unchanged.


## 0.1.0

First Sonovect release candidate.

- Local audio/video-soundtrack ASR with FunASR CPU and Qwen3-ASR GPU routes.
- Durable tasks, timestamps, anonymous speakers and FunASR-compatible JSON, text and SRT.
- Independent AST events, optional experimental emotion2vec/MOSS vocals and weight-free pitch/energy.
- Selected-only model downloads and loading; offline inference after preparation.
- Compact deployment with two base containers, an optional CPU analysis container and independently optional MOSS; distributed recipes remain available.
- One HTTP/CLI/MCP task workflow, a portable agent skill, bilingual setup guides and dated benchmark references.

See [publication status](PUBLICATION.md) for availability.
