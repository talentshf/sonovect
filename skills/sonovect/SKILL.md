---
name: sonovect
description: 使用已配置的 Sonovect 服务转写本地音频或视频音轨，按需翻译、对齐已有文字、理解声音及分析环境音、人声和音高能量，查询任务并读取文字、字幕和独立分析结果。适用于录音转写、音视频声音分析及结果导出；不负责下载网站视频或生成会议纪要。
---

# Sonovect 服务中心

复用现有 Sonovect MCP（模型上下文协议）工具，或 `sonovect` CLI（命令行）。两者连接同一任务服务，不创建另一套模型处理流程。技能随项目版本维护，连接、认证与可读目录由部署者配置；不包含固定主机、个人路径或凭据。

## 选择功能

先读取 `sonovect_capabilities`，命令行对应 `sonovect capabilities`。按当前部署的可用能力选择，不假定所有模型都已安装。

| 需求 | 任务选项 |
| --- | --- |
| 日常语音取文字 | `sonovect_transcribe`，命令行 `sonovect transcribe FILE`；默认跳过说话人与对齐 |
| 时间戳、字幕 | 提交时 `timestamps=word`，说话人仍可关闭 |
| 匿名说话人 | `speakers=true`；按本次录音编号 |
| 翻译到文字 | `translate_to=目标语言`；原文与译文分别保存 |
| 已有文字找时间 | `transcribe=false, alignment_text=原文, language=语言`，最长90秒 |
| 完整声音分类 | `transcribe=false, classify_audio=true`，不筛去人声类别 |
| 声音问答 | `transcribe=false, audio_question=问题`，需已部署真实音频模型，结果需复核 |
| 多声道分开处理 | `channel_mode=independent`，最多八路，不把声道当说话人 |
| 只找人声区间 | `transcribe=false, detect_speech=true` |
| 环境音 | `analyze_sound=true`，独立 AST（环境音模型） |
| 实验性情绪/声线 | `analyze_voice=true`，使用部署选中的 emotion2vec 或 MOSS |
| 音高、相对能量 | `measure_voice=true`，无需情绪模型，可与以上组合 |

文字转写默认开启；时间、说话人与三种附加开关默认均关闭。只做分析时设置 `transcribe=false`，同时开启所需分析项；后端由部署者选型，不能通过任务临时更换。中文情绪继续实验，输出需复核，不当作真实心理状态。视频只处理所选音轨，不识别画面。参数、状态与示例见[使用流程](references/usage.md)。

## 就绪诊断

使用只读 `sonovect_ready` 或 `sonovect ready --details` 读取组件状态。未就绪说明具体错误码，不自动重提任务或重启服务；能力查询不等于运行就绪。详见[使用流程](references/usage.md)。

## 提交与等待

用用户指定的文件提交一次，保存返回的任务编号。MCP 文件必须位于 `SONOVECT_MCP_INPUT_ROOT` 内；缺配置或越界时说明缺口，不扩大目录权限。认证沿用已配置环境或密钥文件，不在聊天、日志或命令参数中输出密钥。

短录音优先用一次调用转写，直接返回文字；不必先提交再领取。长任务也可订阅 `/v1/jobs/{id}/events` 的 SSE（服务端事件），或提交部署者允许的 `callback_url`（完成通知地址）。通知失败只重发通知，不重新推理。等待期间查询同一编号，不因处理未结束重新提交。超时后继续查询原任务。取消用 `sonovect_cancel`。只有用户要求重跑且输入仍保留时，才用 `sonovect_retry` 补做失败、部分成功或已取消任务的未完成处理；已成功来源及阶段保留，`attempts`（尝试历史）可读。不盲重试。

## 读取结果

- `sonovect_result` 的 `layer=result`：FunASR 语音结果，`format=json|text|srt`。
- `layer=analysis`：独立环境音、人声、数值测量、分类、对齐和声音回答，格式为 JSON（结构化文本）。
- `layer=translation`：独立译文；目标词时间不能从原文时间猜造。
- `layer=evidence`：保留的真实词级证据；`layer=attempts` 为尝试历史，`layer=notification` 为通知状态。
- `layer=manifest`：输出产物及其校验清单；输入摘要见任务状态；任务状态从 `sonovect_status` 获取。

MCP 将原结果包在 `data` 中；不要把包装当作正文。环境音、情绪、测量值不插入转写。缺失时间或说话人不能编造，编号只在本次录音内有效。多文件各有时间轴；字幕只对单个具有句级时间的成功来源导出。

`partial`（部分成功）须说明失败来源/阶段并保留成功部分，不把已提交、服务可访问或空分析当作准确性通过。读取产物不重跑模型。需要本地文件时，用 `sonovect export JOB_ID NEW_DIRECTORY` 校验并导出，目标目录必须尚不存在。
