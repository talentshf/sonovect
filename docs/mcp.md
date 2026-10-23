# MCP integration

Product version **0.1.0**; maintained dependency lock **MCP Python SDK 2.3.0**. The server runs with `sonovect-mcp` over stdio and calls the same `/v1` HTTP task service. For executable configuration, authentication, skill installation and a complete example, use [agent setup](agent-setup.md) / [中文接入指南](agent-setup.zh-CN.md).

Configure the executable, `SONOVECT_URL`, one of `SONOVECT_TOKEN`/`SONOVECT_TOKEN_FILE`, and `SONOVECT_MCP_INPUT_ROOT` through the assistant's native secure configuration. No machine-specific paths or credentials are shipped. Without an input root, submission is disabled while reads remain available. Resolved file paths, including symlinks, must stay within the allowed root. An absolute executable path may be needed when the host does not inherit shell PATH.

| Tool | Inputs | Result |
| --- | --- | --- |
| `sonovect_capabilities` | none | Current capability object |
| `sonovect_submit` | paths and shared strict job options; optional idempotency key | Task metadata/ID |
| `sonovect_status` | job_id | State and source details |
| `sonovect_result` | job_id, layer=result/analysis/manifest, format=json/text/srt | Original result inside `data` |
| `sonovect_cancel` | job_id | Current/cancelled state |
| `sonovect_retry` | job_id | Explicit requeued state |

Only the speech layer supports text/SRT; other layers require JSON. `measure_voice`, `analyze_sound`, `analyze_voice` default false and are independent. Query capability discovery first. Poll the returned task, never silently resubmit. Diagnostics use stderr and stdout is reserved for protocol messages. All tools declare input/output schemas and action annotations.

The project-owned [skill](../skills/sonovect/SKILL.md) and its [workflow](../skills/sonovect/references/usage.md) explain functional choices and reading results. The skill uses configured MCP tools or CLI; [installation](agent-setup.md#3-install-the-skill) is separate from installing the Python client. This release supports stdio, not an unauthenticated HTTP MCP transport.
