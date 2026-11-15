# Sonovect 服务中心使用流程

## 接入

客户端通过 `SONOVECT_URL` 选择服务；认证二选一：`SONOVECT_TOKEN` 或仅含令牌的 `SONOVECT_TOKEN_FILE`。由部署者提供，不搜索其他应用凭据，不将真实值写入示例。MCP 使用标准输入输出，其文件根由 `SONOVECT_MCP_INPUT_ROOT` 限定。

先查能力，关注 `sound_analysis`、`voice_analysis`、`voice_backend`、`voice_measurements`、输入限制及 `options_schema`。能力不可用时说明部署缺口，不静默忽略任务开关。

## 一次调用与标准接入

普通语音用 `sonovect_transcribe`，参数 `path` 加可选 `language`、`prompt`（拼写上下文），直接返回 `text` 和任务号。CLI（命令行）对应 `sonovect transcribe clip.wav`。

软件选择 OpenAI 兼容 STT（语音转文字），填部署者提供的 `/v1` 基址、令牌和 `/v1/models` 返回的模型标识；文件路径为 `/v1/audio/transcriptions`。支持 json/text、srt/vtt、diarized_json；Qwen 的 verbose_json 仅支持显式 word 粒度，不编造 Whisper 诊断字段。`stream=true` 仅用于 json，按真实完成的识别片段输出；最终全文保持一致。

默认仅取文字；时间与说话人均关闭。要字幕，提交 `timestamps=word`；要说话人，开 `speakers=true`。独立分析设置 `transcribe=false` 并开启分析项。

## MCP

将以下参数传给 `sonovect_submit`，路径替换为用户已指定且位于允许目录内的文件：

```json
{"paths":["/allowed-input/clip.mp4"],"speakers":true,"analyze_sound":true,"analyze_voice":false,"measure_voice":true,"audio_track":0}
```

记录返回的 `id`。`audio_track` 为从零开始的音轨序号，对同一任务各文件生效；不是声道或说话人。`language`、`hotwords` 是模型相关提示，不保证命中。可用 `idempotency_key` 防网络重试重复提交，同一个键不能用于不同输入或参数。

调用 `sonovect_status`，参数为 `{"job_id":"JOB_ID"}`。`queued`、`running` 继续查原编号；终态有 `succeeded`、`partial`、`failed`、`cancelled`、`expired`。

调用 `sonovect_result`：

```json
{"job_id":"JOB_ID","layer":"result","format":"text"}
```

读取声音分析改为 `layer=analysis, format=json`；字幕为 `layer=result, format=srt`；清单为 `layer=manifest, format=json`。非语音层不支持文本/字幕。返回 `{ "data": ... }`，内容与网络接口一致。

## 命令行

```sh
sonovect capabilities
sonovect submit clip.wav --wait
sonovect submit clip.mp4 --audio-track 0 --analyze-sound --measure-voice --wait
sonovect submit clip.wav --analyze-voice --wait
sonovect status JOB_ID
sonovect wait JOB_ID --timeout 7200
sonovect result JOB_ID --format json
sonovect result JOB_ID --format text
sonovect result JOB_ID --format srt
sonovect analysis JOB_ID
sonovect export JOB_ID new-result-directory
```

`--speakers` 请求说话人计算，`--timestamps word` 请求词级对齐，默认都关闭；`--language English` 指定语言提示；`--hotword Sonovect` 可重复。三个附加开关互不隐式开启，安装模型不等于每次运行。

需要取消或明确重跑时用 `sonovect cancel JOB_ID` / `sonovect retry JOB_ID`。过期输入无法重跑，需要重新提供原文件。重试保留已经完成的来源及阶段，只补未完成处理；尝试历史通过 `layer=attempts` 读取。模型若已调整，补做阶段使用当前明确配置。

## 输出

语音 JSON 为来源列表，包括 `key`、`text`、可用的 `timestamp`、`sentence_info`。时间均为原媒体起点的整数毫秒，音轨延迟已计入；不插值补造缺失对齐。SRT（字幕格式）需要句级起止时间。

分析统一为 `audio-analysis-v1`：`stages.events`、`stages.vocal`、`stages.measurements` 分别为 `completed|failed|not_requested`；`engines` 记录成功阶段模型/算法；整体 `status` 为 `completed|partial|failed|not_requested`。事件在 `events`，情绪在 `emotions`，声线在 `voice`，数值在 `measurements`。

数值带算法、窗口、单位和可用状态。音高为 Hz（赫兹），能量为 dBFS（相对数字满幅分贝），不代表校准响度、人物身份、健康或真实情绪。无语音、证据不足可能没有数值或观察；空结果不证明现场没有声音。

通过能力查询读取部署情况，包括 `execution.layout`。紧凑部署使用两个基础容器，CPU附加分析和MOSS分别按需选用；容器分组不改变任务开关、结果层次或重试语义。能力缺失时说明所需的部署选项，不在提交媒体任务时自行启动服务或下载模型。

## 就绪与故障诊断

开始处理前可调用只读 `sonovect_ready`，或 `sonovect ready`；需要组件详情时使用 `details=true`，命令行对应 `sonovect ready --details`。复用现有令牌，无需扩大可读文件目录。报告 `status=not_ready` 是已获取的诊断结果，依据 `code`（错误码）、`component`（故障组件）、`errors`（必要失败）和 `warnings`（可选警告）说明原因；不能据此自动重提任务、重启容器或修改宿主。就绪探测不加载模型，`model_inference_verified=false` 不代表本次已有任务失败。旧服务不支持详情时会返回 `details_supported=false`，只能解释实际提供的信息。

## 完成通知

长任务可在提交时传 `callback_url`，CLI 对应 `--callback-url`。只接受部署者配置的 HTTPS 主机和 443 端口；回调正文为终态事件，读取产物继续使用原任务号。签名为 `Sonovect-Signature: v1=HMAC-SHA256(token, timestamp + "." + body)`，时间戳在 `Sonovect-Timestamp`，接收方检查时效并按事件编号去重。重发同一事件不重推理；最多自动尝试八次。

也可连接 `/v1/jobs/JOB_ID/events`，携带 `Last-Event-ID` 断线续读。服务主动通知只代表处理完成；离线唤醒智能体或发消息须由消费者已有事件入口接收。


## 翻译、对齐、分类和声音问答

均通过 `sonovect_submit` 的处理选项调用；读取前先确认能力已配置。

```sh
sonovect submit clip.wav --translate-to en --wait
sonovect translation JOB_ID
sonovect submit clip.wav --no-transcribe --language zh --alignment-text "已有文字" --wait
sonovect submit clip.wav --no-transcribe --classify-audio --classify-top-k 5 --wait
sonovect submit clip.wav --no-transcribe --audio-question "录音中主要发生了什么？" --wait
sonovect submit stereo.wav --channel-mode independent --wait
```

MCP 参数对应 `translate_to`、`translation_context`、`alignment_text`、`classify_audio`、`classify_top_k`、`audio_question`、`channel_mode`。翻译用 `layer=translation` 读取，其他新增结果位于 `layer=analysis` 的 `alignment`、`classification`、`understanding`。声音问答直接读取音频，不把文字稿推理冒充听到了声音。分类为未校准分数，按最长十秒窗口做时长加权平均；环境音分析则保留窗口范围并筛去语音标签。

`sonovect wait` / `submit --wait` 消费 SSE（服务端事件）完成通知。超时、断线后查询原任务，服务仍可能正在处理，不重提。各阶段实际成功与模型准确性分开；声音理解及情绪输出要复核。

## 实时与其他软件

OpenAI（开放接口）使用 `/v1/realtime?intent=transcription`，24kHz单声道原始16位音频。已配置神经语音检测时可自动判断停顿；否则或客户端主动选择时用 `input_audio_buffer.commit`。定稿前的增量是已提交录音段的识别结果，不保证说话未结束时逐字出草稿。

Deepgram（语音接口协议）使用 `/v1/listen`，文件支持原始上传及独立声道；实时只提供定稿，支持自动停顿或显式 `Finalize`，不提供虚构的可信度。FunASR（语音工具包）使用 `/v1/funasr` 的离线原始音频协议；不冒充在线两遍模型。Home Assistant（家庭自动化平台）通过可选 Wyoming（本地语音设备协议）桥接；声音分类软件用 Hugging Face（模型平台）标准音频分类客户端。原生 STT（语音转文字）配置与智能体工具共用能力，但不会让代理自动获得重配、下载或部署权限。
