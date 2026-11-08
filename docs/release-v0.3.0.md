# Sonovect v0.3.0 — VibeVoice-ASR and optional realtime recognition

Sonovect v0.3.0 adds optional Microsoft VibeVoice-ASR support and authenticated
realtime recognition through the service and `sonovect stream` CLI. Qwen remains
the default file-transcription route. VibeVoice Streaming 1.5B is an **on-demand
alternative**, with a separate runtime and no automatic container restart.

## Included capabilities

- **VibeVoice-ASR Streaming 1.5B:** pinned model assets and upstream runtime,
  continuous 16-to-24 kHz resampling, native chunk/lookahead handling and final
  tail flushing. Preserve model-emitted anonymous speaker labels; no word or
  sentence timestamps are invented.
- **Realtime service and CLI:** authenticated `/v1/realtime`, bounded mono
  16 kHz PCM16 input, replaceable full-text drafts and a final result. Read a WAV
  file or live PCM from stdin. The Qwen route provides text only. The client
  does not automatically open a microphone, reconnect or resubmit a file job.
- **Original VibeVoice-ASR file adapter:** connect to an operator-managed
  official vLLM endpoint and retain durable task lookup, signed compatible
  results, sentence timing and recording-local speakers. Default admission is
  900 seconds per source, with no automatic chopping or word interpolation.
- **Separate runtime dependencies:** clean test and live environments explicitly
  include the WebSocket transport. Optional GPU SDKs are not forced into the
  core client or existing file worker.

The existing native file API, opt-in DashScope-compatible asynchronous interface,
CLI/MCP file workflow and independent acoustic outputs remain available.

## Setup and measured limits

See the bilingual [runtime guide](vibevoice-realtime.md) / [中文指南](vibevoice-realtime.zh-CN.md)
for pinned assets, authentication, session semantics and foreground start/stop.
The release includes adapters, asset metadata and recipes. Prepare and qualify
the isolated GPU runtime separately; it is not included in the default file
deployment. No prebuilt realtime image or model weights are distributed.

The 1.5B required asset set is approximately 5.64 GB. A dated RTX3090 / 24 GiB
short-sample check passed through the actual model, service and CLI. Its English
process reached 5004.9 MiB allocated / 5262 MiB reserved in the PyTorch allocator,
excluding other GPU allocations. A Chinese sample misrecognized “甚至” as
“山治”; its reused events have no retained timing/memory measurement. These
checks do not establish Chinese meeting quality, multi-speaker accuracy,
eight-minute stability, microphone latency or production-image acceptance.

Realtime sessions are transient, limited to one per process, default to
300 seconds and have no resume or automatic retry. VibeVoice 1.5B has a hard
480-second configuration ceiling. It does not supply aligned timestamps or
acoustic analysis. There is no browser recording UI or Sayflit realtime page.
The original VibeVoice file route does not support optional acoustic stages.

## Security review

The refreshed image scan retains an explicit low-severity GCC parser limitation, [CVE-2026-115456](https://security-tracker.debian.org/tracker/CVE-2026-115456), with no current Debian fix. The exact-library and restricted-service assessment does not repair the library or exclude native decoder denial of service. See the [scoped review and required evidence](security/os-assessment.md#newly-observed-gcc-parser-limitation). Optional realtime images remain a separate operator qualification scope.

## Distribution and existing deployments

Release attachments contain source ZIP, clean public Git history bundle, Python
wheel, source distribution, standalone agent skill, the existing share cover and
`SHA256SUMS`. Verify downloaded artifacts before installing. Containers build
locally; this release does not publish registry images or a package to PyPI.
Publishing or downloading v0.3.0 does not upgrade an existing deployment or
install/activate an agent skill. Existing releases and tags remain fixed.

## 中文说明

v0.3.0 正式纳入微软 VibeVoice-ASR 适配，以及服务与 CLI（命令行）实时识别。
VibeVoice Streaming 1.5B（流式小版）作为备选：独立环境、按需启动、前台退出后
删除容器，不自动重启，不加入默认常驻部署。默认文件转写继续使用 Qwen。

实时命令接收标准 WAV（音频容器）或持续输入的 PCM（原始采样），先返回可替换
草稿，结束后返回定稿。1.5B 保留模型原生匿名说话人标签，不补造时间戳。
会话暂不持久化、不支持恢复或自动重试；默认300秒，每进程一个会话，1.5B 配置
不得超过480秒。客户端不自动打开麦克风，本次没有浏览器录音或 Sayflit 实时页面。

1.5B 完整文件约5.64GB；RTX3090 的英文短测中，PyTorch（张量框架）预留显存
峰值约5.14GiB，不含其他显卡分配。中文样例存在误识别，长会话、多人、中文会议
效果和生产实时镜像仍须单独验证。原版 VibeVoice 文件适配独立使用官方 vLLM
（模型推理框架）服务，默认每文件900秒，暂不支持附加声音分析。

发行提供适配代码、模型清单和配方，模型及显卡运行环境另行准备；七项附件附带
摘要校验，不上传公共容器镜像或 PyPI（Python 软件包索引）。本次发布不会切换
现役服务、修改默认连接或自动安装代理技能。
