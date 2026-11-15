# Architecture and responsibility

```mermaid
flowchart LR
  C[HTTP / CLI / MCP / Skill] --> A[Container 1: API + durable SQLite queue]
  A --> W[Container 2: speech worker]
  W --> F[Native CPU FunASR]
  W --> Q[Qwen: coordinator + segmentation + ASR processes]
  W --> E[Optional container 3: selected CPU analysis processes]
  Q --> E
  W --> M[Optional independent MOSS GPU container]
  Q --> M
```

Compact is the default single-host layout: two base containers, one optional CPU analysis container, and optional MOSS. FunASR and Qwen are alternative speech selections. Analysis starts only enabled AST, emotion2vec and numerical processes; MOSS is selected instead of emotion2vec. The measurements-only image contains no model frameworks or weights. Model assets are prepared separately at pinned revisions, verified and loaded lazily on requested inference.

The API authenticates, validates and admits durable jobs. The speech container owns bounded media decoding and queue processing. Qwen uses separate supervised coordinator, segmentation and ASR processes with a shared reviewed dependency closure; segmentation and ASR bind only loopback. Separate processes preserve lazy model state and GPU unload boundaries. The supervisor starts the queue worker only after helpers are ready, monitors every child, drains the queue worker before stopping helpers and fails the unit if a child exits. Container restart preserves durable jobs and leases. CPU analysis processes share one container resource ceiling but retain independent endpoints, thread controls, errors and request counters. A failed analysis stage leaves successful speech and sibling results available.

`--layout distributed` is an explicit advanced option for independent service placement/scaling. It uses the same source, pinned models and job/result contracts. Container boundaries are deployment choices; no client owns a second queue or bypasses the job API. The external-provider recipe delegates model processing to an explicitly compatible private coordinator.

AST always owns environmental tags. One vocal backend is selected per deployment: CPU emotion2vec or independent GPU MOSS. Numerical processing requires no weights and reuses existing speech intervals. Qwen unload is confirmed before MOSS starts; MOSS releases its GPU model after requests by default. Combining containers does not reduce weight size or promise lower latency. Internal HTTP serialization remains between isolated model processes.

Speech and analysis artifacts are separate, immutable on retrieval and checked during export. Models, job data, configuration and source have separate storage responsibilities. This repository contains current product source, docs, contracts, tests and `skills/sonovect`; private planning and retired development material live outside the product tree.

## Service center processing

Standard OpenAI, Deepgram, FunASR offline and HF adapters translate supported requests into the same processing contracts. File adapters use durable jobs; live committed speech turns use bounded ephemeral sessions and the existing speech owner. Wyoming is an optional protocol bridge, not another recognition worker.

The default file plan is speech activity plus recognition, without speaker features, forced alignment or auxiliary analysis. Requested word/speaker processing and independent channels are explicit. Supplied-text alignment can omit recognition. Translation persists source speech before calling the operator-selected text service; audio questions send real normalized audio to the selected audio-input model. Results stay in separate layers.

A compact Qwen worker can host the pinned text-only Omni Thinker. It and the configured local text-translation proxy hold the same GPU coordination lock and confirm release of their own incompatible models before use. External model credentials/addresses are operator configuration, never caller-selected URLs. CPU analysis-only jobs avoid this GPU lock. File/turn transcription shares one ASR owner; this does not make a non-online decoder produce word drafts.

Stage checkpoints, attempt history and replayable SSE preserve completed work. An independent signed-notification outbox retries delivery without rerunning inference. Queue admission, uploads, session counts and turn lengths are bounded. Completion publication, transport delivery and user/agent wake remain separate states.
