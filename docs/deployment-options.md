# Hardware and deployment choices

Supported recipes target Linux amd64 and Python 3.12. CPU route uses Paraformer/FSMN/punctuation with optional CAM++; Qwen route needs NVIDIA runtime and sufficient VRAM for ASR/alignment. Existing measurements were made on an RTX3090 with24GiB, not a guarantee for every GPU. ARM/macOS model deployment is not qualified by these Linux images.

AST runs in the optional CPU analysis container (about346MB weights). emotion2vec is an optional CPU model (about1.12GB weights). MOSS4B/8B needs additional GPU capacity; setup budgets12288/19456MiB with reserve and model-specific free-memory floors. These are allocator settings, not complete-process capacity guarantees. Numeric measurement is CPU-only with no model weights, a measurements-only image without model frameworks; compact analysis defaults to a shared2CPU/6GiB ceiling, while distributed measurements default to2CPU/2GiB. Consult [all controls](configuration.md) before tuning.

Both speech routes default to2base containers. Any CPU analysis combination adds one; MOSS adds its own GPU container. `--layout distributed` retains independent service scaling; choose it explicitly only when needed. Container counts do not predict total model memory.

Use local speech-only when minimizing dependencies; add AST when event tags matter; add independent measurements for numeric cues; select a vocal backend only when its experimental output is useful. Larger MOSS does not have demonstrated superior emotion quality. Qwen 0.6B trades resources for weaker measured quality. Nativev2.0.9 is a configuration variant, not new checkpoint bytes.

The external-provider recipe runs API/media workers against an existing compatible private coordinator. Operators own endpoint trust, source compatibility, model assets and actual inference acceptance. Offline installation requires transporting the exact selected cache layouts and accepted images, then hash verification and real inference on the destination.
