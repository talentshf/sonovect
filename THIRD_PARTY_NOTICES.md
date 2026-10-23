# Third-party dependencies and models

Project-authored code is licensed under Apache-2.0. Installing a dependency or
fetching a model does not relicense that component. No model weights, upstream
Git history, reference voices or real recordings are distributed here.

| Component | Integration | Upstream license/source |
| --- | --- | --- |
| FunASR | Optional native Python backend; bundled VAD/speaker worker | [MIT code license](https://github.com/modelscope/FunASR/blob/main/LICENSE); model terms are separate |
| Paraformer, FSMN VAD, CT punctuation, CAM++ | Models fetched by FunASR/ModelScope | Consult the exact checkpoint's model card and license before use |
| Qwen3-ASR and ForcedAligner | Native Transformers model integration and fixed `-hf` checkpoint downloads | [Apache-2.0](https://github.com/QwenLM/Qwen3-ASR/blob/main/LICENSE) and [model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf) |
| MOSS-Audio | Pinned source repackaged as `0.1.0+sonovect.1` for inference; original authors/declaration retained; runtime license text unresolved | [Apache-2.0 model card](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-4B-Instruct) |
| FireRedVAD | Optional pinned CPU VAD package and model files | [Apache-2.0 code](https://github.com/FireRedTeam/FireRedVAD/blob/main/LICENSE) and [checkpoint](https://huggingface.co/FireRedTeam/FireRedVAD) |
| MCP Python SDK | Optional stdio server | [MIT](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) |
| FFmpeg | Verified 9.0.2 source build in media/native queue images; source, build script and LGPL notice included | [License and build-dependent terms](https://ffmpeg.org/legal.html) |
| RapidFuzz | Optional offline edit-distance scoring | [MIT](https://github.com/rapidfuzz/RapidFuzz/blob/main/LICENSE) |
| FastAPI, HTTPX, Pydantic, Uvicorn | Runtime libraries | See the licenses in their installed distributions |
| NumPy, SciPy, scikit-learn, PyTorch and model tooling | Optional model or test libraries | See the exact distribution licenses |

`providers/speech` contains project-authored inference orchestration and
adapters. Upstream model implementations are installed from their original
sources rather than copied into this repository. The maintained paths are Qwen ASR, CAM++ speaker embeddings, FSMN/FireRedVAD segmentation independent CPU AST events and optional MOSS vocal/emotion analysis.

The FFmpeg build configuration and matching source digest are in
[media provenance](docs/security/media-build.json). External encoder libraries
retain their own distribution notices. The source archive in the runtime image
corresponds to the executable built there; do not remove required license/source
materials when redistributing a modified container. MOSS packaging/compatibility
changes are explicit in `providers/speech/moss-worker/prepare_runtime.py`.


## Debian source backports in maintained containers

The maintained images retain the util-linux 2.42.4, ACL 2.4.0 and ncurses 6.6 source backports on Debian13.
Their original and Debian copyright/license notices remain with the installed
packages and corresponding source; they are not relicensed as Apache-2.0.
Source hashes and the complete packaging changes/recipe are in
`providers/speech/shared/os-security`. Each runtime retains the exact modified
corresponding source packages, build instructions and inventories under
`/usr/local/share/sonovect-os-security`. These materials are readable by the
unprivileged service user. Redistributors must preserve the applicable source,
copyright, license and relinking obligations; do not strip these materials from
images. The retained source and recipe allow recipients to rebuild the supplied
libraries and tools. Runtime inventories and scan coverage are described in the
[current review](docs/release-readiness.md).

## Optional AudioSet classifier

`MIT/ast-finetuned-audioset-10-10-0.4593`, revision `f826b80d28226b62986cc218e5cec390b1096902`, is offered under BSD-3-Clause by its upstream model card. Selected weights are downloaded separately; no weights or benchmark audio are bundled in source packages. See the fixed catalog and [upstream model card](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593). Labels/scores have the limitations documented in configuration.

The maintained library build includes exact-source glibc 2.43-7, SQLite 3.53.4-2 and the pinned upstream negative-length CRC patch to zlib 1.3.1. Modified corresponding source archives, packaging changes, build inventory and recipes remain inside each image at `/usr/local/share/sonovect-os-security/`. Container distribution must retain the applicable LGPL/GPL/BSD/zlib notices and source obligations. Build stages include development tools that are excluded from the immutable runtime.


## Experimental emotion2vec+ base weights

`emotion2vec/emotion2vec_plus_base`, fixed revision `b318240bfe67db81a8c572ecb37ce9c3759b81c9`, is an optional separately downloaded CPU vocal model. Its Hugging Face card declares `other` / `model-license` and links to the FunASR repository, not a fixed license file. A fixed official ModelScope card declares Apache-2.0 for the same main-weight SHA256; its label file differs only by a final newline. These different source declarations have not been reconciled by the rightsholder. Do not silently relabel the current selected asset bundle or assume the toolkit's MIT code license covers it. No weights are bundled in source/wheels/images. The [current model-license review](docs/model-licenses.md) records all13 options, evidence hashes and commercial-service/download/redistribution distinctions. Default setup does not select or download emotion2vec.

## MOSS runtime source declaration

The fixed source revision `5cbb1d823937cd5b5de3d8fa4d3a7253ebd3b883` references a missing `LICENSE` file in its pyproject metadata. Its README declares Apache-2.0 for models; no separate code-license text is present in that tree. The optional derived runtime now explicitly uses `LicenseRef-OpenMOSS-Unconfirmed`, retains the original inference source tree, README, declaration, derived metadata and compatibility script inside its image. This marker does not grant rights. Model-card declarations and source-runtime redistribution are separate; commercial redistribution of this optional image remains unconfirmed. It is not deployed by default. No inquiry has been sent.

The OCI image license label identifies the project-authored integration code; it is not a license grant for every contained dependency. Actual component declarations, retained notices/source, proprietary runtime terms and unresolved markers must be reviewed separately.
