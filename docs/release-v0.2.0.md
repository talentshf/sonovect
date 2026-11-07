# Sonovect v0.2.0

Sonovect v0.2.0 adds an opt-in single-file DashScope-compatible asynchronous
transcription interface. Applications can submit a managed HTTPS audio URL,
retain the returned task ID, poll that same task and download a signed result.
The existing native `/v1` API, speech formats and independent sound-analysis
results remain available. This is a file-task service for one trust domain.

## Compatible file transcription

- Authenticated model discovery, asynchronous submission and original-task polling.
- Expiring result links restricted to one task artifact, signed with a separate
  persistent key; result downloads do not require the service bearer token.
- One recognition with separate native and compatible result views. Sentence,
  word and speaker fields contain actual evidence; missing alignment stays absent.
- Inline vocabulary hints, a fixed served model identity and honest capability
  and media-limit declarations. Hints do not guarantee recognition quality.
- Durable input integrity, engine revisions and options. Identical idempotent
  requests recover the original task; native retry cannot replace published
  compatible results. Polling retained tasks can renew result links.
- Exact input-host allowlists, public-address checks, pinned downloads, rejected
  redirects and bounded input size, disk and time. Signed URLs remain private.

Enable the [compatible interface](filetrans-compatibility.md) explicitly and
combine the selected base recipe with `deploy/compose.filetrans.yml`. Keep the
same persistent signing key across restarts, upgrade API/worker/provider metadata
together, and drain compatible tasks before an application rollback. Existing
native task identifiers and results are retained through the additive store change.

The compatibility subset does not include real-time WebSocket recognition,
synchronous or multi-file recognition, vendor uploads, billing or managed
vocabulary resources. A consumer must separately verify its network path,
source policy and recording quality. Existing dated model-quality references
remain dated references; this release does not establish universal parity with
another model or quality for representative Chinese, long or multi-speaker audio.

## Security and distribution

The API image disables access logging that could expose signed result query
strings. [The release dependency update](security/release-020-advisories-20261107.md)
uses fixed SQLite/zlib sources and removes package-manager entry points. Remaining
service and C++ findings retain their explicit runtime boundaries. Source review
does not replace actual-image qualification.

Release attachments provide source, public Git history, the Python wheel, a
source distribution and the standalone agent skill. Check them with `SHA256SUMS`.
Container recipes build locally; model weights remain separate. This release
does not publish prebuilt registry images or a PyPI package. Publishing the
release does not switch an existing service deployment.

The v0.1.0 and v0.1.1 tags and published artifacts remain fixed.

## 中文说明

v0.2.0 正式包含 DashScope（百炼服务协议）单文件异步兼容接口：提交音频地址、按原任务编号查询、通过限时签名链接下载结果。原生 `/v1` 接口、语音结构与独立声音分析继续保留。

兼容任务固定输入摘要、真实引擎修订和参数；同一识别提供原生与兼容视图。已有结果不会被原生重跑覆盖，重启后沿原编号恢复。句段、词时间和说话人仅输出已有真实证据，缺失部分不伪造。即时热词属于模型提示，不承诺命中率或质量等价。

管理员须显式启用、配置精确输入域名和独立持久签名密钥；公开加密入口由部署者配置。像取件码一样，结果链接只允许下载指定的一份产物，不能用于查询其他任务。详见[中文兼容指南](filetrans-compatibility.zh-CN.md)。

本次提供源码、公开版本历史包、Python（编程语言）安装包、源码安装包、独立技能及摘要清单。模型权重另行下载，容器按配方构建；此次不向公共镜像仓或 PyPI（Python 软件包索引）上传。发行包可用与现役服务升级分别判定；既有服务不会因创建发行而自动切换。

此版本不包含实时转写、完整厂商资源平台或预编译词表服务。中文、多人、长录音及业务热词质量仍须用对应素材验收。
