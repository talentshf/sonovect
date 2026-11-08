# Release scope

Sonovect maintains one v0.3.0 product, the native `/v1` task API, an opt-in compatible asynchronous file API, optional realtime sessions and one `audio-analysis-v1` contract. Public distribution status is recorded in [PUBLICATION.md](../PUBLICATION.md).

| Area | Maintained reference |
| --- | --- |
| Installation and model selection | [Deployment](../deploy/README.md), [configuration](configuration.md) |
| Interfaces and output | [HTTP](api.md), [MCP](mcp.md), [results](results.md) |
| Agent integration | [Client and skill installation](agent-setup.md) |
| Measured quality | [Benchmarks](quality.md), [reference data](../evaluation/reference-results.json), [reproduction](release-acceptance.md) |
| Development and packaging | [Validation](validation.md), [contributing](../CONTRIBUTING.md) |
| Security and component sources | [Security](../SECURITY.md), [OS assessment](security/os-assessment.md), [component records](model-licenses.md) |

The retained library findings have completed project-side assessment and mitigation within the supported file-service boundary. Upstream limitations remain documented for dependency maintenance. Chinese emotion remains an optional experiment. Supported recipes target Linux amd64. File tasks remain the default; the [optional Qwen and VibeVoice-ASR realtime adapters](vibevoice-realtime.md) require separate GPU runtimes and explicit activation. VibeVoice 1.5B is an on-demand alternative, with no automatic restart or default resident service. No browser console is provided. The realtime runtime, model quality and production image are separate qualification scopes; file-image findings do not attest those optional runtimes.
