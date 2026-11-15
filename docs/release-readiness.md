# Release scope

Sonovect v0.4.0 provides with standard transcription/translation/audio-question APIs, shared-model realtime transcription, durable native jobs, documented protocol adapters and one staged `audio-analysis-v1` contract. Public distribution status is recorded in [PUBLICATION.md](../PUBLICATION.md).

| Area | Maintained reference |
| --- | --- |
| Installation and model selection | [Deployment](../deploy/README.md), [configuration](configuration.md) |
| Interfaces and output | [HTTP](api.md), [MCP](mcp.md), [results](results.md) |
| Agent integration | [Client and skill installation](agent-setup.md) |
| Measured quality | [Benchmarks](quality.md), [reference data](../evaluation/reference-results.json), [reproduction](release-acceptance.md) |
| Development and packaging | [Validation](validation.md), [contributing](../CONTRIBUTING.md) |
| Security and component sources | [Security](../SECURITY.md), [OS assessment](security/os-assessment.md), [component records](model-licenses.md) |

The retained library findings have completed project-side assessment and mitigation within the supported file-service boundary. Upstream limitations remain documented for dependency maintenance. Chinese emotion remains an optional experiment. Supported recipes target Linux amd64. File tasks remain the default. Shared-model realtime transcription is explicitly enabled against the current speech owner and adds no recognition model; the older [experimental Qwen and VibeVoice-ASR realtime adapters](vibevoice-realtime.md) require separate GPU runtimes and explicit selection. VibeVoice 1.5B is an on-demand alternative, with no automatic restart or default resident service. No browser console is provided. The realtime runtime, model quality and production image are separate qualification scopes; file-image findings do not attest those optional runtimes.

The [0.4.0 release guide](release-v0.4.0.md) separates the 14-role image and package qualification from selected four-role deployment and actual model/client checks. Installation checks use a synthetic engine; they do not establish model accuracy or device acceptance.
