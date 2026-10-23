<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/brand/butterfly-dark.svg"><img src="assets/brand/butterfly-color.svg" alt="Sonovect purple butterfly" width="240"></picture></p>
<p align="center"><strong>Sonovect · Sound, structured.</strong></p>

[English](README.md) · [完整配置](docs/configuration.zh-CN.md) · [部署](deploy/README.md) · [测试参考](docs/quality.zh-CN.md) · [智能体接入](docs/agent-setup.zh-CN.md) · [交流讨论](https://github.com/talentshf/sonovect/discussions) · [参与贡献](CONTRIBUTING.md#中文)

[![Checks](https://github.com/talentshf/sonovect/actions/workflows/checks.yml/badge.svg)](https://github.com/talentshf/sonovect/actions/workflows/checks.yml) · [Apache-2.0](LICENSE) · Python 3.12+ · [v0.1.0 发行介绍](docs/release-v0.1.0.md)

# 用自己的硬件，部署可媲美云端的语音识别服务

**Sonovect v0.1.0 是本地部署的 ASR（自动语音识别）组装平台。** 把录音或视频音轨转换为文字、时间戳和可选的匿名说话人，提供 FunASR 结构结果、纯文本和 SRT（字幕）；环境音、人声及数值测量独立输出。通过 HTTP（网络接口）、CLI（命令行）或 MCP（模型上下文协议）接入同一任务流程。

用自己的 CPU（处理器）或 NVIDIA GPU（图形处理器）运行模型，掌握录音、结果与保留期限。准备好权重后，识别在本地完成，无需云端 ASR。已有同素材对照中，本地 Qwen1.7B 的转写质量与所测云端服务相当，中文会议的字符错误更少：

| 2026-10-21 同素材对照，错误越少越好 | 本地 Qwen1.7B | 百炼 Fun-ASR | 百炼 Qwen3-ASR |
| --- | ---: | ---: | ---: |
| 39分钟中文会议，8073参考字符 | **7.42%** | 8.40% | 7.78% |
| 12段英文，241参考词 | **0词错误** | 1词错误 | **0词错误** |

三者使用相同单声道音频和评分规则；本地硬件为 RTX3090 / 24GiB。结果是所测素材的参考值，具体配置、非语音表现和复现方法见[测试参考](docs/quality.zh-CN.md)。环境音与实验情绪单独评测。

部署时分别选择语音路线、AST环境音、人声后端和无权重测量。**只下载选中的模型，只运行任务请求的功能。** emotion2vec与MOSS均为可选实验功能。当前发行状态见[发布说明](PUBLICATION.md)。

## 常用部署只需2～3个容器

CPU与Qwen两条语音路线都以**接口/任务队列、语音处理两个容器**起步。需要AST环境音、emotion2vec或音高能量时，增加**一个CPU附加分析容器**，功能可以自由组合。MOSS继续作为独立可选显卡容器，全配最多四个。只选音高能量时使用不含Torch、FunASR和情绪权重的轻量镜像。

| 选择 | 容器数 |
| --- | ---: |
| CPU或Qwen，只转写 | 2 |
| 转写＋任意CPU附加分析组合 | 3 |
| 转写＋MOSS，不选CPU附加分析 | 3 |
| 转写＋CPU附加分析＋MOSS | 4 |

默认`--layout compact`（紧凑部署）保留容器内部的模型进程隔离；只启动选中的分析模块，收到相应任务才加载权重。需要独立扩容时可选`--layout distributed`（分服务部署）。配置生成会列出对应配方、容器数量、模型身份和下载体积。

## 输入、选择与输出

| 输入 | 可选处理 | 输出 |
| --- | --- | --- |
| WAV、FLAC、MP3、M4A/AAC、OGG/Opus、AIFF | 语言提示、热词、匿名说话人 | FunASR语音JSON、纯文本、字幕 |
| MP4、MOV、MKV、WebM、AVI | 选择音轨并处理声音，不分析画面 | 同样的语音结果及独立分析 |
| 混合语音、音乐与环境声 | AST环境音、实验人声、音高与能量分别开启 | 独立的 `analysis.json`，各阶段有状态和来源 |

按内容探测格式，实际编码支持由媒体工作器决定。默认最多16文件、总计256MiB、每文件解码两小时；声道下混单声道，不当作说话人身份。模型缺失的时间或说话人字段省略，不编造。

## 如何选

| 需求 | 部署选项 | 单次任务 |
| --- | --- | --- |
| 中文、无显卡起步 | `--route cpu --sound none --voice none` | 默认只转写 |
| 多语与显卡 | `--route qwen --speech 1.7b` | 默认只转写 |
| 环境音 | `--sound ast` | `--analyze-sound` |
| CPU实验情绪 | `--voice emotion2vec` | `--analyze-voice` |
| GPU开放式人声描述 | `--voice 4b` / `--voice 8b` | `--analyze-voice` |
| 无权重音高、能量 | `--measurements` | `--measure-voice` |

配置生成默认选Qwen1.7B、紧凑部署和AST，人声与测量关闭；任务三个附加开关均关闭。一个部署选一个人声后端；AST不借MOSS重复分类，数值测量无需情绪模型。Qwen0.6B、Paraformer配置与VAD（语音活动检测）的替代选项、阈值和全部参数见[完整选型表](docs/configuration.zh-CN.md)。

## 快速开始

需要Python3.12或更新版本、Docker（容器工具）及Compose（编排插件）。从源码目录执行，CPU路线：

```sh
python -m pip install '.[mcp]'
sonovect setup --route cpu --sound ast --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
```

配置文件含随机令牌，权限0600。客户端通过部署者配置的 `SONOVECT_URL` 与 `SONOVECT_TOKEN_FILE`（或令牌环境变量）连接；客户端不会自动读取 `deploy/.env`。完整连接示例见[智能体与客户端接入](docs/agent-setup.zh-CN.md)。Qwen路线另需受支持NVIDIA环境，见[部署手册](deploy/README.md)。

```sh
sonovect capabilities
sonovect submit clip.mp4 --analyze-sound --wait
sonovect status JOB_ID
sonovect result JOB_ID --format text
sonovect result JOB_ID --format srt
sonovect analysis JOB_ID
sonovect export JOB_ID new-result-directory
```

任务在后台持久执行，查询和导出不会重新识别。输入默认终态后保留24小时、结果7天，可配置。部分失败明确保留成功结果；取消、重试与幂等提交见[用法](docs/usage.zh-CN.md)。当前提供文件任务服务，没有浏览器操作台或实时流式接口。

## 语音与分析分开

语音接口 `/v1/jobs/{id}/result` 返回来源列表：

```json
[{"key":"audio_0000","text":"你好。","timestamp":[[100,450]],"sentence_info":[{"text":"你好。","start":100,"end":500,"spk":0}]}]
```

这是格式示例。附加接口 `/v1/jobs/{id}/analysis` 统一使用 `audio-analysis-v1`，包含 `events`、`emotions`、`voice`、`measurements`，以及每阶段状态和模型/算法身份。声音标签不插入正文，时间均为原媒体起点的整数毫秒。数字信号测量不等于真实情绪、身份、健康或校准响度。

## 助手接入与开发

部署完成后，按[智能体接入指南](docs/agent-setup.zh-CN.md)安装客户端、配置 MCP 并安装同版本 [Sonovect技能](skills/sonovect/SKILL.md)。技能指导智能体选型、提交、等待和读取结果；它不包含模型或凭据。发行提供标准 MCP 服务和独立技能包，使用支持本地标准输入输出的智能体即可接入。

## 一起参与

欢迎一起让本地语音识别更容易部署、适配更多硬件。可以到[讨论区](https://github.com/talentshf/sonovect/discussions)分享部署经验，在[问题区](https://github.com/talentshf/sonovect/issues/new/choose)报告可复现的问题，也可以完善指南、翻译或已有接入方式。第一次参与开源也欢迎，从[贡献指南](CONTRIBUTING.md#中文)开始即可。

[文档导航](docs/README.md) · [架构](docs/architecture.md) · [运维](docs/operations.md) · [安全](SECURITY.md) · [组件来源](docs/model-licenses.md) · [开发贡献](CONTRIBUTING.md) · [发行状态](PUBLICATION.md)
