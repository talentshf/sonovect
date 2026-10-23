# Product introduction / 产品介绍

## English

**Cloud-class speech recognition. Your own hardware.**

Sonovect is a self-hosted ASR service for recordings and video soundtracks. Turn your CPU or NVIDIA GPU into a local transcription service with Qwen3-ASR or FunASR, timestamps, anonymous speakers and subtitles. Add AST sound events, experimental vocal analysis or pitch/energy measurements independently, with separate structured results.

Choose the models you need, prepare their fixed assets and load them on request. A typical deployment uses two or three containers. Applications and agents share the same HTTP, CLI and MCP task workflow; the included Sonovect skill explains feature selection, submission and result retrieval.

The same-audio [reference comparison](quality.md) shows local Qwen1.7B matching the tested cloud services on English and making fewer errors on the Mandarin meeting. Results retain their dates, configurations and denominators; environmental sounds and experimental emotions have separate evaluations.

## 中文

**用自己的硬件，部署可媲美云端的语音识别服务。**

Sonovect 是面向录音和视频音轨的本地 ASR（自动语音识别）服务。利用已有 CPU（处理器）或 NVIDIA GPU（显卡），通过 Qwen3-ASR 或 FunASR 完成转写，输出时间戳、匿名说话人和字幕。环境音、实验人声分析、音高能量分别选择、独立输出，方便应用和智能体读取。

按选型下载固定模型、按请求加载运行，常用部署只需两到三个容器。HTTP（网络接口）、CLI（命令行）和 MCP（模型上下文协议）共用一套任务流程，附带的 Sonovect skill（技能）说明选功能、交任务和读结果的方法。

已有[同素材参考测试](quality.zh-CN.md)中，本地 Qwen1.7B 的英文结果与所测云端服务相当，中文会议字符错误更少。说明保留测试日期、配置和分母；环境音及实验情绪的结果另列。

## GitHub About / 仓库简介

> Local ASR on your hardware | 本地部署语音识别：Qwen3-ASR / FunASR, audio & video transcription, speakers, subtitles and independent sound analysis. Docker · HTTP · CLI · MCP · Agent Skill.

Repository / 仓库：<https://github.com/talentshf/sonovect>

The README is the product landing page: choose English or 中文, compare configurations, inspect dated benchmarks, deploy, then connect an agent. No separate website is required. / 项目首页即介绍页：中英文切换、配置比较、测试参考、部署和智能体接入集中可达，无需另建网站。

## Topics / 搜索主题

```text
asr speech-recognition speech-to-text self-hosted local-asr offline-asr
funasr qwen3-asr speaker-diarization audio-processing audio-event-detection
video-transcription subtitles mcp docker python audio-analysis emotion-recognition
ai-agent model-context-protocol
```

These 20 topics describe implemented interfaces and optional capabilities; emotion recognition remains experimental. Public discovery begins after the repository is made public. No promise of search ranking, popularity or broader quality superiority is implied.

这20个主题覆盖已有接口与可选功能；情绪识别保持实验标识。仓库公开后才面向公众被搜索发现，不承诺搜索排名或所有场景的质量优势。
