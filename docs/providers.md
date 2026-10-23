# Providers

The public integration surface is `/v1/jobs`, CLI and MCP. Services under `providers/speech` form the versioned internal runtime; build matching source revisions. They do not own customer identities, meetings or downstream business workflows.

| Role | Responsibility |
| --- | --- |
| coordinator | Serializes GPU speech/vocal work and combines stage envelopes |
| segmentation | CPU VAD and CAM++ recording-local speaker segmentation |
| qwen | Pinned Qwen ASR and forced alignment |
| events | Independent CPU AST event tags |
| vocal | Optional CPU emotion2vec, reusing speech intervals |
| sound | Optional GPU MOSS vocal observations; no duplicate event generation |
| measurements | Independent CPU signal algorithms without model weights |

Runtime health is not proof of loaded weights or real inference. Missing/corrupt assets, capacity limits and malformed outputs fail explicitly. Models are pinned and byte-verified; normal inference is offline. Internal ports stay private; only the authenticated job API is published. [Configuration](configuration.md) lists all supported controls. A provider integration must preserve the generated public output contracts and per-stage failure boundaries.

Default compact deployment groups these responsibilities into one speech unit and one optional CPU analysis unit. Processes and model state remain isolated; model weights still load only on requested inference. MOSS stays an independent GPU service. Advanced distributed recipes keep separate service placement without changing any public job or output interface.
