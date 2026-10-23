# Sonovect v0.1.0 使用流程

## 接入

客户端通过 `SONOVECT_URL` 选择服务；认证二选一：`SONOVECT_TOKEN` 或仅含令牌的 `SONOVECT_TOKEN_FILE`。由部署者提供，不搜索其他应用凭据，不将真实值写入示例。MCP 使用标准输入输出，其文件根由 `SONOVECT_MCP_INPUT_ROOT` 限定。

先查能力，关注 `sound_analysis`、`voice_analysis`、`voice_backend`、`voice_measurements`、输入限制及 `options_schema`。能力不可用时说明部署缺口，不静默忽略任务开关。

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

`--no-speakers` 关闭说话人输出；`--language English` 指定语言提示；`--hotword Sonovect` 可重复。三个附加开关互不隐式开启，安装模型不等于每次运行。

需要取消或明确重跑时用 `sonovect cancel JOB_ID` / `sonovect retry JOB_ID`。过期输入无法重跑，需要重新提供原文件。重跑可能使用当前部署模型，不是原来那次推理的另一种导出。

## 输出

语音 JSON 为来源列表，包括 `key`、`text`、可用的 `timestamp`、`sentence_info`。时间均为原媒体起点的整数毫秒，音轨延迟已计入；不插值补造缺失对齐。SRT（字幕格式）需要句级起止时间。

分析统一为 `audio-analysis-v1`：`stages.events`、`stages.vocal`、`stages.measurements` 分别为 `completed|failed|not_requested`；`engines` 记录成功阶段模型/算法；整体 `status` 为 `completed|partial|failed|not_requested`。事件在 `events`，情绪在 `emotions`，声线在 `voice`，数值在 `measurements`。

数值带算法、窗口、单位和可用状态。音高为 Hz（赫兹），能量为 dBFS（相对数字满幅分贝），不代表校准响度、人物身份、健康或真实情绪。无语音、证据不足可能没有数值或观察；空结果不证明现场没有声音。

通过能力查询读取部署情况，包括 `execution.layout`。紧凑部署使用两个基础容器，CPU附加分析和MOSS分别按需选用；容器分组不改变任务开关、结果层次或重试语义。能力缺失时说明所需的部署选项，不在提交媒体任务时自行启动服务或下载模型。
