# Reproduce the benchmarks

[Measured results](quality.md) · [中文测试参考](quality.zh-CN.md) · [Reference JSON](../evaluation/reference-results.json)

## Speech corpus and scoring

[evaluation/public-corpus.json](../evaluation/public-corpus.json) fixes 24 public cases, source revisions, reference text, event aliases and SHA-256 of normalized audio:

| Group | Cases | Reference |
| --- | ---: | --- |
| LibriSpeech test-clean | 12 | Fixed IDs/offsets; published human transcripts |
| AISHELL-4 | 1 full 39-minute meeting | S_R004S01C01, small room R004; published turn annotations |
| ESC-10 | 10 | One clip per category and predeclared acceptable labels |
| Digital silence | 1 | Deterministic zero-signal control |

Obtain media from the original sources under their terms. Place mono 16kHz PCM16 WAV files at `audio/<sha256>.wav` relative to a working copy of the manifest, and verify the listed hashes. Media and detailed outputs stay outside the source checkout. Configure an isolated service and the client URL/token as in [agent setup](agent-setup.md).

From the source directory, install scoring dependencies. Run the remaining commands from your evaluation directory, using the actual path to the source checkout:

```sh
python -m pip install '.[evaluation]'
# In your evaluation directory: dataset.json and audio/ contain the selected corpus.
python /path/to/sonovect/scripts/run_benchmark.py dataset.json run \
  --dataset-sha256 FROZEN_MANIFEST_SHA256 --run-id reference --version 0.1.0
sonovect-evaluate dataset.json run/predictions.json score.json
```

Compute `FROZEN_MANIFEST_SHA256` after choosing local paths, before inference. The runner verifies manifest/audio hashes, keeps job IDs for resumption, and checks export hashes. It sends only audio and declared options; scoring against reference answers is offline. [Accuracy evaluation](accuracy-evaluation.md) defines normalization, denominators, speaker alignment and missing predictions.

## Acoustic studies

[The acoustic protocol](quality-protocol.md) records the fixed RealDESED and CSEMOTIONS sources, selection seed, model identity, mappings, independent development/test splits and scoring rules. These studies have different denominators from the speech corpus. Their aggregate counts and configuration are in [reference-results.json](../evaluation/reference-results.json); use the original sources for media. Benchmark dates remain the dates measured, including when a later package retains the same implementation.

## Validated product scope

The accepted Linux amd64 deployment supports CPU and NVIDIA speech routes, compact/distributed layouts and independent optional analysis. Validation covers HTTP/CLI/MCP submission and retrieval, subtitles, export integrity, restart persistence, empty-cache preparation and selected model combinations. Hardware requirements are in [deployment choices](deployment-options.md); developer commands are in [validation](validation.md).

Version 0.1.0 identifies the product; exact source revisions, image identities and package checksums identify builds. Model-quality references do not replace functional installation checks on a different machine. Publication availability is recorded in [PUBLICATION.md](../PUBLICATION.md).
