# Changelog

## Unreleased

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
