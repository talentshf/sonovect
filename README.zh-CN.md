<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/brand/butterfly-dark.svg"><img src="assets/brand/butterfly-color.svg" alt="Sonovect purple butterfly" width="240"></picture></p>
<p align="center"><strong>Sonovect · Sound, structured.</strong></p>

[English](README.md) · [接入清单](docs/connections.md#中文接入清单) · [部署](deploy/README.md) · [智能体接入](docs/agent-setup.zh-CN.md) · [测试参考](docs/quality.zh-CN.md)

[![Checks](https://github.com/talentshf/sonovect/actions/workflows/checks.yml/badge.svg)](https://github.com/talentshf/sonovect/actions/workflows/checks.yml) · [Apache-2.0](LICENSE) · Python 3.12+ · [0.4.1版本说明](docs/release-v0.4.1.md)

# 自己的语音处理服务，多种标准方式接入

**Sonovect 是可以自行部署的语音处理服务，提供转写、翻译成文字和声音理解。** 在熟悉的软件里配置接口，让智能体处理录音，或用命令行批量提交文件，按需拿到文字、字幕、译文和独立的声音分析。

日常一句话走轻量流程：不默认计算说话人特征、不加载词对齐器、不做额外声音分析。Qwen 识别模型默认空闲驻留30分钟；本地翻译和声音理解等重型处理会协调自己的模型交接，适应共享显卡。

正式版本 [v0.4.1](https://github.com/talentshf/sonovect/releases/tag/v0.4.1)提供客户端、源码和独立智能体技能。功能范围与验证边界见[0.4.0说明](docs/release-v0.4.0.md)。本项目不包含语音生成。

## 按用途选功能

| 你想做什么 | 得到什么 |
| --- | --- |
| 发一句语音，直接取文字 | 一次调用转写，默认自动判断语言 |
| 处理长录音、多个文件 | 持久任务、持续等待事件、按任务号找回和显式重试 |
| 做字幕或定位原音 | SRT/VTT（字幕格式）、句段/词时间、已有稿件独立对齐 |
| 整理多人或左右声道 | 本次录音内的匿名说话人、各声道独立文字与时间 |
| 听外语录音、取得译文 | 标准接口译成英文，任务选项可指定其他目标语言；原文另存 |
| 连续输入麦克风 | 手动结束一段，或检测停顿后返回这一段的文字 |
| 判断有人说话、有哪些声音 | 独立人声检测、环境事件、声音分类、音高与能量 |
| 询问录音中发生了什么 | 声音模型直接听音频、回答文字；推断需要复核 |

情绪和人声观察仍是实验能力。部署者选择服务可提供的模型，调用者选择本次要执行的处理；[能力查询](docs/api.md)返回实际支持的选项、语言与限制。

## 在现有工具里接入

| 工具或场景 | 接入方式 | 当前支持范围 |
| --- | --- | --- |
| OpenAI 兼容软件 | 文件转写、翻译、音频问答接口 | 文字、字幕、英文译文、一段音频加一个问题 |
| OpenAI Realtime（实时接口） | `/v1/realtime?intent=transcription` | 手动提交或神经人声检测断句后识别 |
| Deepgram（语音接口）客户端 | `/v1/listen` | 上传文件、实时连接返回完整分段、可选独立声道 |
| FunASR（语音识别协议）客户端 | `/v1/funasr` | 离线音频分段，不伪装在线或双遍模式 |
| Home Assistant（家庭自动化平台） | 可选 Wyoming（本地语音协议）桥接 | 可信内网的原生语音识别协议 |
| Hugging Face（模型平台）客户端 | `/models/ast-audioset` | AudioSet（声音类别集）分类分数 |
| 长录音应用 | 可选 DashScope（百炼协议）兼容 `/api/v1` | 受控音频地址、异步文件任务 |
| 智能体与自动化 | CLI（命令行）、MCP（模型上下文协议）、随包技能 | 相同处理选项、任务和结果 |

这些是已经实现的协议子集。实际推理由部署者配置的本地模型或上游服务完成，兼容某家接口不代表会调用该公司的云服务。地址、密钥填写方法与限制见[接入清单](docs/connections.md#中文接入清单)。

## 开始部署

准备 Python 3.12+、Docker（容器运行工具）和 Compose（容器编排）。在源码目录执行以下 CPU（处理器）示例，无需显卡：

```sh
python -m pip install '.[mcp]'
sonovect setup --route cpu --sound ast --write deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
```

配置工具会创建受保护的配置文件及随机服务令牌。客户端另行配置 `SONOVECT_URL` 与 `SONOVECT_TOKEN_FILE`，不会自动读取部署配置。使用 Qwen GPU（显卡）识别时，选择 `--route qwen` 和对应[部署配方](deploy/README.md)。翻译、声音理解与可选桥接需按文档准备相应配置和模型。

```sh
sonovect capabilities
sonovect transcribe voice.wav
sonovect submit meeting.mp4 --speakers --timestamps word --wait
sonovect submit recording.wav --translate-to en --wait
sonovect submit sound.wav --no-transcribe --classify-audio --wait
sonovect result JOB_ID --format srt
sonovect translation JOB_ID
sonovect export JOB_ID new-result-directory
```

默认只转文字；需要字幕、多人或分析时再开启。独立声音分析可以完全不做转写。文件流式返回真实完成的文字块；实时接口按已提交的语音段返回，当前共享引擎不提供句中逐词修订草稿。辅助阶段失败时保留原文和已完成结果。主动完成通知已有签名与重试，需配置接收方和允许域名；不会自动唤醒智能体。

## 模型与运行方式

默认识别路线为 Qwen3-ASR，可选原生 FunASR CPU 路线；独立的 VibeVoice/Qwen 实验实时运行时仍须单独选择和准备。词对齐、说话人特征按需加载。AST（声音分类模型）负责环境声音，emotion2vec（情绪模型）或 MOSS（人声描述模型）提供可选实验观察。紧凑 Qwen 工作器可启用固定版本的 Qwen2.5-Omni 理解部分，只输出文字；也可配置兼容的音频理解或文字翻译服务。

常用部署是两个基础容器加可选 CPU 分析容器；Wyoming 桥接另加一个小容器，共用原识别模型。权重按选型、固定版本另行下载，不进入源码或安装包。[完整配置](docs/configuration.zh-CN.md)和[组件来源](docs/model-licenses.md)记录具体选择。

## 效果与参与

[测试参考](docs/quality.zh-CN.md)保留原语料、日期和配置，不把旧识别测试当成翻译、实时或声音问答准确率。声音理解可能误解语义或猜测声音来源；信号测量不等于身份、健康、情绪事实。

欢迎在[讨论区](https://github.com/talentshf/sonovect/discussions)分享部署，在[问题区](https://github.com/talentshf/sonovect/issues/new/choose)报告可复现问题，或[参与贡献](CONTRIBUTING.md#中文)。项目首页就是产品介绍，无需另外注册账号或使用独立网站。

[文档导航](docs/README.md) · [架构](docs/architecture.md) · [运维](docs/operations.md) · [安全](SECURITY.md) · [发行状态](PUBLICATION.md)
