# Connection checklist / 接入方式清单

## English

One configured service can supply standard application interfaces and agent tools. Use `GET /v1/models` and authenticated `GET /v1/capabilities` to discover the deployed model, tasks, language support and limits. Examples below use the compact Qwen route, whose speech model is `qwen3-asr`; another route may advertise a different name.

| Client | Address to configure | Model / protocol |
| --- | --- | --- |
| OpenAI file/audio client | Service root + `/v1` | `qwen3-asr` for transcription/English translation; configured audio-input model for questions |
| OpenAI transcription session | Service WebSocket root + `/v1/realtime?intent=transcription` | 24kHz mono PCM16; commit manually or enable neural speech endpointing |
| Deepgram SDK | HTTP root and WebSocket root of the same service | `/v1/listen`, configured speech model; files or final speech turns |
| FunASR client | WebSocket root + `/v1/funasr` | `offline`; mono PCM16 at 8/16kHz; client ends a turn |
| Hugging Face InferenceClient | HTTP root + `/models/ast-audioset` | Uploaded audio or supported base64 input, AudioSet scores |
| Home Assistant | Host and port of the optional Wyoming bridge | Default10300; trusted local network, no protocol authentication |
| DashScope file application | Service root + `/api/v1` | Explicitly enabled controlled-URL asynchronous file protocol |
| CLI / MCP agent | `SONOVECT_URL` = service root; protected `SONOVECT_TOKEN_FILE` | `sonovect` / `sonovect-mcp`; MCP also needs `SONOVECT_MCP_INPUT_ROOT` |
| Custom workflow | `POST /v1/jobs`, `GET /v1/jobs/{id}/events` and artifacts | Upload once, keep the job ID, wait or reconnect |

For example, an OpenAI-compatible application uses `http://127.0.0.1:8096/v1` and the operator's API key. CLI/MCP use the root `http://127.0.0.1:8096` instead. Remote deployments should use their configured TLS endpoint. Keep credentials in the consuming product's native secret store; do not place them in URLs. Bearer authentication applies to HTTP/WebSocket APIs; Deepgram's Token scheme is also accepted for its adapter. The optional Wyoming bridge is a separate trusted-network interface.

### How results arrive

A short file can return text in one request. File SSE returns genuinely completed transcript chunks and final text. A realtime session returns transcription after a committed speech turn; it does not supply online word drafts. Durable jobs expose replayable events, results and explicit retry. A synchronous timeout returns the existing job ID rather than asking the client to duplicate the request. Signed HTTPS callbacks have their own retries and require an operator allowlist/receiver; ordinary file response and event waiting do not depend on callbacks.

Audio-input Chat Completions currently supports one user message containing one audio and one question, text output only, with a configured duration limit (default60 seconds). Translation uses a separately configured text service after speech recognition, and retains the source. Capabilities reflect configuration, not a promise of accuracy. See [usage](usage.md), [configuration](configuration.md) and [agent setup](agent-setup.md).

## 中文接入清单

| 你想怎么使用 | 填什么或选什么 | 得到的结果 |
| --- | --- | --- |
| 在软件里配置转写 | 选 OpenAI 兼容接口，基址填“服务地址＋`/v1`”，填原生保存的密钥及模型 | 文字、时间、字幕；功能取决于软件本身支持 |
| 让智能体处理录音 | 安装同版客户端和技能，配置 CLI（命令行）或 MCP（模型上下文协议） | 转写、翻译、说话人、分析等组合选项 |
| 接入长录音应用 | 可选百炼兼容连接，或原生任务接口 | 后台任务、原任务号恢复、结果导出 |
| 接入实时工具 | 配置 OpenAI 实时、Deepgram（语音接口）或 FunASR（离线语音协议）地址 | 发送一段、返回一段；共享引擎没有逐词修订草稿 |
| 接入家庭设备 | 添加 Wyoming（本地语音协议）主机和端口，默认10300 | 可信内网语音识别，共用已有模型 |
| 接入声音分类工具 | Hugging Face（模型平台）客户端的模型地址填“服务地址＋`/models/ast-audioset`” | AudioSet（声音类别集）原始类别分数 |
| 开发自己的程序 | 常用功能走对应标准接口；组合处理走 `/v1/jobs` | 使用同一服务、任务状态和结果 |

普通调用只转文字，制作字幕时再开启时间处理，整理多人时再开启说话人。声音分析可以关闭转写独立运行。英文翻译走标准音频翻译接口，其他目标语言由任务选项指定；原文不被译文覆盖。已有稿件对齐需提供文字、指定语言并关闭重新转写。需要语义理解时使用真实音频问答，回答需复核。

短语音直接响应，长任务按同一任务号等待事件或查询，流式输出返回真实完成的片段。主动完成回调必须配置接收方和允许域名，不能把已有回调能力当成已经唤醒智能体。所有支持范围以本次部署的能力查询为准；未实现的厂商选项明确拒绝。

[中文用法](usage.zh-CN.md) · [完整配置](configuration.zh-CN.md) · [智能体接入](agent-setup.zh-CN.md) · [当前版本范围](release-v0.4.0.md)
