# 使用与结果读取

Sonovect v0.3.0。先配置服务入口 `SONOVECT_URL`，认证二选一：令牌环境变量或仅含令牌的 `SONOVECT_TOKEN_FILE`；客户端不自动读取部署配置。先用 `sonovect capabilities` 检查能力。

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `language` | null | 模型支持的语言提示 |
| `speakers` | false | 录音内匿名说话人 |
| `hotwords` | [] | 最多200条、每条1–80字符的提示 |
| `audio_track` | 0 | 从零开始的音轨序号，对所有来源生效 |
| `analyze_sound` | false | 独立AST环境音 |
| `analyze_voice` | false | 部署选中的实验性emotion2vec/MOSS |
| `measure_voice` | false | 独立无权重音高/能量 |

三个附加开关互不隐式开启；布尔值不能用字符串，未知字段拒绝。一个部署选一个人声后端，任务不能临时换模型。缺能力在接单前拒绝。视频只处理所选音轨，声道下混单声道。

Qwen（通义千问）的术语用于提示识别，不是需要插入正文的内容。程序按
[官方文档](https://huggingface.co/docs/transformers/v5.20.2/model_doc/qwen3_asr#context--hotwords)
给词表加上明确标签，但模型仍可能出现[上下文混入输出](https://github.com/QwenLM/Qwen3-ASR/issues/186)。
片段输出连续词表项或较长的上下文原句时，程序仅对同一音频片段撤掉全部上下文再识别一次，
再为最终文字生成时间对齐；不会直接删除命中的术语。录音中真实说出的词表可以在复核后保留，
正常单个术语不触发复核。复核沿用同一模型与任务，仅可疑片段增加推理，不新建任务，也不修改旧结果。
该防护减少提示回显，不保证所有术语都识别正确，弱声或歧义语音仍需人工核对。
复核失败时该来源处理失败，不把已知可疑输出当作成功结果。

```sh
sonovect submit clip.wav --no-speakers --wait
sonovect submit clip.mp4 --audio-track 0 --analyze-sound --measure-voice --wait
sonovect submit clip.wav --language English --hotword Sonovect --analyze-voice
sonovect wait JOB_ID --timeout 7200
sonovect status JOB_ID
sonovect result JOB_ID --format json
sonovect result JOB_ID --format text
sonovect result JOB_ID --format srt
sonovect analysis JOB_ID
sonovect export JOB_ID new-directory
sonovect cancel JOB_ID
sonovect retry JOB_ID
```

提交返回持久任务编号；`queued`、`running`继续查同一编号。终态为成功、部分成功、失败、取消、过期；超时不重复提交。`--idempotency-key`用于完全相同输入/参数的重试，不同内容复用同一键会冲突。`retry`明确重算仍保留的输入，可能使用当前模型；读取和导出不重算。

字幕需要单一成功来源和句级时间，多文件时间轴不能直接拼接。导出目标目录必须新建并核对摘要。部分成功保留有效语音，明确指出失败来源/阶段。默认16文件、总计256MiB、每文件解码7200秒，终态后输入24小时、结果168小时。完整参数见[配置](configuration.zh-CN.md)。

## 0.4 用户接入清单

通用客户端从 `/v1/models` 获取实际模型名称；智能体使用同一套处理选项。日常一句话用标准转写即可，默认不计算说话人、字词对齐或声音分析。

| 想做什么 | 软件直接配置 | 智能体或命令行 |
| --- | --- | --- |
| 快速取文字 | OpenAI（开放接口）`/v1/audio/transcriptions` | `sonovect transcribe FILE` |
| 字幕、找原话位置 | `srt`、`vtt`、`verbose_json` 的词时间 | `submit --timestamps word` |
| 区分说话人 | `diarized_json`；Deepgram（语音协议）`diarize=true` | `submit --speakers` |
| 翻译录音 | `/v1/audio/translations` 标准入口译成英文 | `submit --translate-to LANGUAGE` 可选其他目标语言 |
| 给声音打标签 | Hugging Face（模型平台）的音频分类客户端，地址 `/models/ast-audioset` | `submit --no-transcribe --classify-audio` |
| 问录音里有什么 | 音频输入的聊天补全，选已配置的理解模型 | `submit --no-transcribe --audio-question QUESTION` |
| 已有文字找时间 | 采用独立扩展，没有冒称统一厂商协议 | `submit --no-transcribe --language zh --alignment-text TEXT` |
| 通话左右声道分开 | Deepgram 文件参数 `multichannel=true` | `submit --channel-mode independent` |
| 只要语音或说话人时间线 | 独立任务选项 | `submit --no-transcribe --detect-speech` 或 `--speakers` |
| 测音高和相对能量 | 独立测量结果 | `submit --no-transcribe --measure-voice` |
| 长录音后台完成 | 任务事件订阅或签名完成回调 | `submit --wait` 或 `--callback-url URL` |
| 连续发送录音段 | OpenAI 实时转写 `/v1/realtime?intent=transcription` | `stream FILE`，输入24kHz单声道16位音频 |
| 既有 Deepgram 软件 | `/v1/listen` 文件上传；实时不提供在线草稿，可自动判断停顿 | 可自动判断停顿，或 `Finalize`（提交当前段）和 `CloseStream`（提交并关闭） |
| 既有 FunASR 软件 | `/v1/funasr`，`mode=offline`，8k/16k原始音频 | 客户端明确结束说话，不提供伪造的在线/两遍纠正 |
| Home Assistant（家庭自动化平台） | 可选 Wyoming（本地语音协议）入口，默认10300端口 | 共用同一识别模型，由设备或平台判断录音结束 |

统一使用 Bearer（持有者凭据）认证；Deepgram 也接受其标准的 `Token`（令牌）请求头。不把某家厂商的模型名悄悄换成其他模型，不支持的选项会明确拒绝。当前识别模型没有可信度分数，Deepgram 结果不会虚构该字段。原生命令行等待改用 SSE（服务端事件流）完成通知，等待断开不重新提交。

声音分类保留“人声”等全部 AudioSet（声音标签集）类别；按最长十秒窗口的原始分类分数做时长加权平均，并在响应头标明方法。分数未经概率校准。`--analyze-sound` 则输出筛选后的环境声窗口，两者不混用。声音问答直接读取音频；仅接受一条含问题与音频的用户消息、输出文字，暂不接收对话历史、生成参数或流式回答。声音回答需复核，不能当作精确事件时间。情绪与声音形容维持实验标记。

最多八路声道分别生成独立来源键、文字、原始时间和声道编号，不把声道当作说话人。字幕有真实词时间时据此切成可读片段，否则沿用真实语音片段；翻译字幕只沿用原语音片段时间，不伪造译词定位。原文与译文分别读取，失败的翻译可单独重试。

本地翻译模型与识别共享显卡时，将 `SONOVECT_TRANSLATION_URL` 指向识别协调器的 `/translation/v1`，以 `TRANSLATION_BACKEND_URL` 配置实际文本模型的标准 `/v1` 地址。协调器串行调度并确认释放本服务的识别/声音模型后再翻译，避免显存预约互相等待；普通转写仍按驻留时长配置。外部独立计算资源继续直连标准翻译上游。
