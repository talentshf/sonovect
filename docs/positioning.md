# Product introduction / 产品介绍

## English

**Your speech processing service, connected your way.**

Sonovect turns your own hardware into a shared service for transcription, translation into text and sound understanding. Connect existing applications through standard protocol subsets, let an agent handle a recording, or automate file batches. Request text, subtitles, anonymous speakers, translations or separate sound results as needed.

Ordinary transcription avoids unrequested speaker features, alignment and analysis. Applications can use OpenAI-compatible file/audio endpoints, shared-model transcription sessions, Deepgram, FunASR offline turns, Hugging Face audio classification, optional DashScope file tasks or a Wyoming home-device bridge. CLI and stdio MCP expose the same processing options and recoverable jobs.

Speech, translation and observations remain separate. Real streamed events report completed chunks/turns; signed callbacks require an explicit receiver. Audio-question answers and emotional observations require review. The operator selects local models or configured upstreams; protocol compatibility is not a promise to implement every vendor option.

## 中文

**自己的语音处理服务，多种标准方式接入。**

Sonovect 利用自己的硬件，统一提供转写、翻译成文字和声音理解。可以在现有软件里配置标准接口，让智能体处理录音，或通过命令行批量调用；按需取得文字、字幕、匿名说话人、译文和独立的声音分析。

普通转写跳过未请求的说话人、对齐和分析。软件通过 OpenAI 兼容文件/音频接口及实时分段、Deepgram（语音接口）、FunASR（离线识别协议）、Hugging Face（声音分类接口）、可选百炼异步文件协议或 Wyoming（家庭设备语音协议）接入。CLI（命令行）和 MCP（模型上下文协议）提供相同处理选项及可找回的任务。

原文、译文和声音观察分开保存。流式事件返回真正完成的片段；主动通知需配置接收方。声音问答和情绪观察需要复核。推理使用部署者选定的本地模型或上游服务，不把协议兼容描述成支持所有厂商参数。

## GitHub About / 仓库简介

> Self-hosted speech processing: transcription, text translation & sound understanding. OpenAI-compatible APIs · Deepgram · FunASR · Wyoming · CLI · MCP.

Repository / 仓库：<https://github.com/talentshf/sonovect>

The bilingual README is the product introduction. See [connections](connections.md), [0.4.0 scope](release-v0.4.0.md), and [distribution status](../PUBLICATION.md). / 中英文首页就是产品介绍；接入方式、当前能力和正式发行分别说明。

## Topics / 搜索主题

```text
speech-to-text speech-recognition self-hosted transcription audio-analysis
speech-translation audio-understanding openai-compatible deepgram funasr
qwen3-asr speaker-diarization subtitles streaming-asr home-assistant
wyoming-protocol audio-classification mcp docker ai-agent
```

These topics describe available interfaces and optional capabilities, not every vendor feature or broad model-quality guarantees. / 主题描述现有接口和可选能力，不承诺支持厂商全部功能或所有场景的准确率。
