# 0.4.0 — A speech processing service center / 通用语音处理服务中心

Release: **v0.4.0**, 2026-11-15. Download the [official artifacts](https://github.com/talentshf/sonovect/releases/tag/v0.4.0) and verify `SHA256SUMS`.

**2026-11-15正式发行。** [发行页](https://github.com/talentshf/sonovect/releases/tag/v0.4.0)提供源码、干净版本历史、Python安装包、源码安装包、独立智能体技能、分享封面和摘要清单。

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

The formal release gate covers all 14 maintained image roles, including the Wyoming bridge: exact source/version identity, installed OS/Python scans, dependency consistency and source/license inventories. The wheel and source distribution are independently installed without a development-tree mount; HTTP, CLI, MCP, restart recovery and realtime CLI admission are exercised with a synthetic engine. Hosted Python 3.12/3.13 checks qualify the release source separately. See [validation](validation.md) for the gate and reproduction commands.

正式发行覆盖14种维护镜像角色，包括家庭语音桥接；检查准确源码与版本、系统与Python包扫描、依赖一致性及源码许可清单。两个安装包均在不挂开发源码的隔离环境独立安装，以合成引擎验证网络接口、命令行、智能体工具、重启恢复与实时命令接入。托管Python 3.12/3.13检查单独验证发行源码。

所选四角色组合另有真实客户端和处理验证。模型质量仍限于实际样例，不把功能调用通过当成广泛准确率评测。旧基准保留原日期和模型身份；独立实验运行时、完整手机及家庭设备业务验收不在本轮范围内。已评估的系统库残余风险继续按[安全说明](security/os-assessment.md)披露，并非零漏洞声明。

## Upgrading / 升级

Rebuild the selected recipes and update both the service and its client/skill together. Ordinary transcription now defaults to plain text processing; request speaker turns, word timing or analysis explicitly. Review capability discovery, translation/audio-input upstream configuration, optional bridges and the model idle setting rather than copying an old environment unchanged. Back up the existing data with the deployment's native recovery process before upgrading. A clean deployment can use a new data volume; public compatibility APIs do not promise portability of old internal job records or model caches.

按选定配方重新构建，并一起更新服务、客户端与技能。普通转写默认只处理文字，需要说话人、词时间或分析时显式请求。重新核对能力查询、翻译与音频理解上游、可选桥接及模型驻留配置；不要直接沿用旧环境文件。升级前按部署环境原生恢复流程备份现有数据；全新部署可使用新数据卷，标准调用协议不等于旧内部任务或模型缓存具备跨版本迁移承诺。
