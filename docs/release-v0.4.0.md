# 0.4.0 — A speech processing service center / 通用语音处理服务中心

Status: current main-branch source. Separately packaged GitHub releases remain listed in [PUBLICATION.md](../PUBLICATION.md); this source update does not claim a new public artifact set or a full all-role image qualification.

状态：当前主分支源码。已打包的正式版本见[发行状态](../PUBLICATION.md)；源码更新不冒充新附件发行或全角色镜像验收。

## For users / 面向使用者

- Transcribe a quick voice message in one call, without unrequested speaker features or alignment. / 一次调用取文字，跳过未请求的说话人特征与对齐，默认空闲驻留30分钟。
- Request subtitles, anonymous speakers, supplied-text alignment or separate channels. / 按需取得字幕、匿名说话人、已有稿件对齐和独立声道结果。
- Translate speech into text while retaining its source transcript. / 原文与译文分开保存；标准翻译接口目标为英文，任务选项可选其他语言。
- Use standard file and transcription-session clients or ask an agent through CLI/MCP. / 软件配置标准接口，智能体和命令行共用同一服务。
- Detect speech, classify sounds, measure signals or ask a configured audio-input model a question. / 人声检测、声音分类和信号测量可独立执行；声音问答需要复核。
- Recover durable jobs and retry incomplete stages. / 按任务号恢复状态，只重试未完成阶段；流式事件与通知投递分开管理。

[Connection checklist / 接入清单](connections.md) · [Usage / 使用](usage.md) · [中文用法](usage.zh-CN.md)

## Explicit limits / 明确边界

The shared recognition engine returns completed speech turns, not an online word-by-word draft. FunASR compatibility is offline, without two-pass or online emulation. Deepgram interim text and unsupported enhancement options fail explicitly. Audio-input Chat Completions accepts one audio plus a question and returns non-streamed text; it does not generate speech. Sound interpretation and emotion remain subject to review. Wyoming is an optional trusted-network bridge without another recognition model. Completion callbacks require a configured receiver and allowlist; transport support does not prove a user was notified.

共享引擎在一段结束后返回文字，不提供句中逐词修订。FunASR仅离线模式；Deepgram中间草稿及未实现增强参数明确拒绝。音频问答是一段音频加问题、返回非流式文字，不生成声音。声音推断与情绪需复核；家庭设备桥接只供可信内网。完成回调必须配置接收方和允许域名，具备通知机制不等于已经通知用户。

## Verification scope / 验证范围

The selected four-role deployment has exercised native OpenAI/Deepgram/Hugging Face/Wyoming clients, FunASR offline turns, file streaming, independent analysis/alignment, translation and audio questions. Core and provider tests cover admission, authentication, schemas and stage recovery. The default model owner is shared across file and turn-based recognition. The selected runtime reuse adds only the pinned WebSocket transport and optional Wyoming library to reviewed base closures.

所选四角色组合已运行真实客户端和处理验证；模型质量仍限于实际样例，不把功能调用通过当成广泛准确率评测。旧基准保留原日期和模型身份；独立实验运行时、所有13种旧角色的新镜像审计、完整手机/家庭设备业务验收并非这次源码提交的验证范围。
