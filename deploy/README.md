# Deployment

Supported container recipes target Linux amd64/Python 3.12. Install Docker and Compose; the Qwen/MOSS roles additionally require a working NVIDIA driver/runtime. Reuse host tooling; the project does not install drivers or change host proxy rules.

| Recipe | Components |
| --- | --- |
| `compose.yml` | Compact CPU: 2 base containers + optional shared CPU analysis + optional MOSS |
| `compose.qwen.yml` | Compact Qwen: 2 base containers + optional shared CPU analysis + optional MOSS |
| `compose.distributed.yml` / `compose.distributed.qwen.yml` | Explicit advanced split-service CPU/Qwen layouts, selected with `--layout distributed` |
| `compose.external-provider.yml` | API/media worker against an explicitly compatible existing private coordinator |

```sh
python -m pip install '.[mcp]'
sonovect setup --route cpu --sound ast --voice none --measurements --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml --check-hardware
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
python scripts/prepare_deployment.py --compose deploy/compose.yml --verify-only --smoke-audio sample.wav
```

For GPU speech use `--route qwen` and the Qwen recipe. Choose `--voice emotion2vec|4b|8b` explicitly for experimental vocals, or leave off. Numeric measurement is selected separately and downloads no weights. In compact mode it shares the CPU analysis container; distributed measurement-only services retain their own resource ceilings. Setup defaults to Qwen 1.7B, compact layout and CPU AST with per-job events still off, no vocal service and no measurements. One vocal backend per deployment; no duplicate MOSS event work.

Setup creates a new mode-0600 environment with a random token and refuses overwrite. Configure the CLI/MCP endpoint/authentication separately in the consumer's native secure configuration. Only API port 8096 is published, default localhost; model ports remain internal. Operator TLS/auth/request limits are needed for broader exposure. Each installation is one trust domain.

Selected models download only in preparation, at fixed revisions and verified hashes; ordinary runtime uses offline caches. `--plan` shows identities and sizes, `--verify-only` checks existing bytes without writes/network. Explicit model roots are verified directly without duplicating cache downloads. Missing, corrupt or unavailable assets fail clearly. Source/packages/images contain no weights. No component-license confirmation flag is required; source metadata remains informational.

Compact deployments use 2 containers for speech, 3 with any combination of CPU analysis, 3 with MOSS alone, or 4 with CPU analysis and MOSS. Setup prints `compose_file` and `container_count`; use the matching recipe. `COMPOSE_PROFILES=analysis` starts only selected CPU modules. Add `voice` for MOSS. Disabled modules have no listening process, no inference and no model download. The measurements-only compact image remains model-framework-free.

Compact image roles are `qwen`, `analysis` and `analysis-measurements`, plus shared `core`, `native` and optional `sound`. Advanced role images are `core`, `worker`, `native`, `provider`, `segmentation`, `asr`, `events`, `vocal`, `sound`, `measurements`. They share version 0.1.0, run as UID 10001 with dropped capabilities/no-new-privileges, and retain required source/build/notice materials. Build matching source revisions, inspect actual installed packages and scan each role. A healthy worker is not proof of loaded weights, accuracy or free GPU capacity.

Jobs and models use separate volumes. Keep native configuration and existing data until restart, real speech/analysis/export and isolated recovery pass. Do not overwrite newer jobs with old database snapshots. Back up/query SQLite as the service UID. No host-specific deployment paths or credentials are shipped. [Full configuration](../docs/configuration.md), [operations](../docs/operations.md) and [security](../SECURITY.md) describe controls and boundaries.
