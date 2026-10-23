# 使用与结果读取

Sonovect v0.1.0。先配置服务入口 `SONOVECT_URL`，认证二选一：令牌环境变量或仅含令牌的 `SONOVECT_TOKEN_FILE`；客户端不自动读取部署配置。先用 `sonovect capabilities` 检查能力。

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| `language` | null | 模型支持的语言提示 |
| `speakers` | true | 录音内匿名说话人 |
| `hotwords` | [] | 最多200条、每条1–80字符的提示 |
| `audio_track` | 0 | 从零开始的音轨序号，对所有来源生效 |
| `analyze_sound` | false | 独立AST环境音 |
| `analyze_voice` | false | 部署选中的实验性emotion2vec/MOSS |
| `measure_voice` | false | 独立无权重音高/能量 |

三个附加开关互不隐式开启；布尔值不能用字符串，未知字段拒绝。一个部署选一个人声后端，任务不能临时换模型。缺能力在接单前拒绝。视频只处理所选音轨，声道下混单声道。

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
