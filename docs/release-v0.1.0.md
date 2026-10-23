# Sonovect v0.1.0

[English](#english) · [中文](#中文)

## English

**Cloud-class speech recognition, running on your own hardware.** Sonovect turns recordings and video soundtracks into FunASR-compatible transcripts, timestamps, anonymous speakers and subtitles. It combines local ASR models with independent optional sound analysis, with one task workflow for applications and agents.

### What is included

- **Speech:** FunASR CPU and Qwen3-ASR GPU routes, with language hints, hotwords, track selection and optional anonymous speakers.
- **Separate sound analysis:** AST events, optional experimental emotion2vec/MOSS vocals and weight-free pitch/energy. Select deployment components and request each stage independently.
- **Deployment:** two base containers; add one CPU analysis unit when needed. MOSS is an independent optional GPU container. Download selected fixed model assets and load them on request.
- **Durable tasks:** status, cancellation, explicit retry, partial results, retention and verified exports.
- **Integration:** HTTP API, CLI, six MCP tools and the portable Sonovect agent skill. Speech JSON, text and SRT remain separate from `analysis.json`.

### Measured reference

The 2026-10-21 comparison used identical mono audio and scoring. On the 8073-character Mandarin meeting, local Qwen1.7B had **7.42% CER**, compared with **8.40%** for Bailian Fun-ASR and **7.78%** for cloud Qwen3-ASR. On 12 English clips / 241 words, errors were **0 / 1 / 0**. Local hardware was RTX3090 / 24GiB. These are dated sample results; [benchmarks](quality.md) separately describe events, experimental emotions and warm latency.

### Join in

Questions, hardware experiences, documentation improvements and focused fixes are welcome. Visit [Discussions](https://github.com/talentshf/sonovect/discussions) and the [contribution guide](../CONTRIBUTING.md).

### Start here

[Deployment](../deploy/README.md) · [All configuration choices](configuration.md) · [Agent and skill installation](agent-setup.md) · [Results](results.md)

Release attachments contain source, a clean single-commit Git bundle, the client wheel, source distribution and standalone skill. `SHA256SUMS` identifies the exact bytes; model weights and private media are not included. Install the client with `python -m pip install './sonovect-0.1.0-py3-none-any.whl[mcp]'`, then follow the agent guide to configure your service.

Supported recipes target Linux amd64; clients use Python 3.12+. This is a file-task service. Chinese emotion remains experimental. Security reporting and current distribution availability are described in [SECURITY.md](../SECURITY.md) and [PUBLICATION.md](../PUBLICATION.md).

## 中文

**用自己的硬件，部署可媲美云端的语音识别服务。** Sonovect 将录音和视频音轨转为兼容 FunASR 的文字、时间戳、匿名说话人和字幕；本地语音模型与可选声音分析按需组合，应用与智能体共用同一任务流程。

### 首版能力

- **语音转写：** FunASR CPU（处理器）路线与 Qwen3-ASR GPU（显卡）路线，支持语言提示、热词、音轨选择和可选匿名说话人。
- **独立声音分析：** AST 环境音、可选实验 emotion2vec/MOSS 人声、无需模型权重的音高能量；部署选型与单次任务开关分别设置。
- **部署方式：** 两个基础容器，需要时增加一个 CPU 分析容器；MOSS 单独可选。只下载所选固定模型，按请求加载运行。
- **任务管理：** 状态查询、取消、显式重试、部分结果、保留期限和导出校验。
- **智能体接入：** HTTP（网络接口）、CLI（命令行）、六个 MCP（模型上下文协议）工具及 Sonovect skill（技能）；语音 JSON（结构结果）、文字、SRT（字幕）与 `analysis.json` 分开读取。

### 测试参考

2026-10-21 同素材对照使用相同单声道音频和评分规则。8073参考字符的中文会议中，本地 Qwen1.7B 的 CER（字符错误率）为 **7.42%**，百炼 Fun-ASR 为 **8.40%**，云端 Qwen3-ASR 为 **7.78%**；12段英文／241参考词的词错误数依次为 **0 / 1 / 0**。本地显卡为 RTX3090 / 24GiB。数字对应所测素材；[测试参考](quality.zh-CN.md)另列环境音、实验情绪和暖机延迟。

### 一起参与

欢迎交流使用与硬件经验、完善文档和提交针对性的修复，第一次参与开源也欢迎。请看[讨论区](https://github.com/talentshf/sonovect/discussions)与[贡献指南](../CONTRIBUTING.md#中文)。

### 开始使用

[部署](../deploy/README.md) · [全部配置与建议](configuration.zh-CN.md) · [智能体与技能安装](agent-setup.zh-CN.md) · [输出说明](results.md)

附件提供源码包、单提交 Git（版本管理）历史包、客户端安装包、源码安装包和独立技能包；`SHA256SUMS`用于文件摘要校验，不附带权重或私密媒体。安装客户端后，按接入指南配置已有服务地址、令牌和输入目录。

支持的服务配方面向 Linux amd64，客户端需要 Python3.12+；当前提供文件任务处理，中文情绪继续实验。[安全说明](../SECURITY.md)与[发布状态](../PUBLICATION.md)记录反馈方式及当前可用范围。
