# Release scope

Sonovect maintains one v0.2.0 product, the native `/v1` task API, an opt-in compatible asynchronous file API and one `audio-analysis-v1` contract. Public distribution status is recorded in [PUBLICATION.md](../PUBLICATION.md).

| Area | Maintained reference |
| --- | --- |
| Installation and model selection | [Deployment](../deploy/README.md), [configuration](configuration.md) |
| Interfaces and output | [HTTP](api.md), [MCP](mcp.md), [results](results.md) |
| Agent integration | [Client and skill installation](agent-setup.md) |
| Measured quality | [Benchmarks](quality.md), [reference data](../evaluation/reference-results.json), [reproduction](release-acceptance.md) |
| Development and packaging | [Validation](validation.md), [contributing](../CONTRIBUTING.md) |
| Security and component sources | [Security](../SECURITY.md), [OS assessment](security/os-assessment.md), [component records](model-licenses.md) |

The retained library findings have completed project-side assessment and mitigation within the supported service boundary. Upstream limitations remain documented for dependency maintenance; they are not an outstanding project repair list. Chinese emotion remains an optional experiment. Supported recipes target Linux amd64; this release provides file tasks for one trust domain, with no real-time streaming or browser console.
