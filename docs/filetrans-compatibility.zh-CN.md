# 标准异步文件转写兼容接口

此入口兼容 DashScope（百炼服务协议）的单文件异步语音识别请求：提交、查询同一任务、下载结果。它与原生 `/v1` 共用持久任务和同一次识别，分别提供原生与兼容结果。范围不包含 FunASR 的 WebSocket（长连接实时通信）、同步转写、厂商上传、账单或预编译词表资源管理。

[接口结构](../contracts/openapi-v1.json) · [English](filetrans-compatibility.md)

| 方法 | 路径 | 认证与用途 |
| --- | --- | --- |
| GET | `/api/v1/models` | Bearer（持有者令牌）认证；读取模型能力和限制 |
| POST | `/api/v1/services/audio/asr/transcription` | 同上，另带 `X-DashScope-Async: enable`；提交任务 |
| GET | `/api/v1/tasks/{task_id}` | 同上；查询原任务 |
| GET | `/filetrans-results/{task_id}` | 单份产物的限时签名；无需服务令牌 |

## 启用与连接

默认不开启。管理员配置 `SONOVECT_COMPAT_MODEL`（单个稳定模型名）、`SONOVECT_COMPAT_PUBLIC_URL`（服务对外 HTTPS 加密地址，不含 `/api/v1`）、`SONOVECT_COMPAT_INPUT_HOSTS`（逗号分隔的输入域名精确列表）及 `SONOVECT_COMPAT_SIGNING_KEY_FILE`（独立持久签名密钥文件）。未配置时兼容入口返回 503；原生功能仍可用。

签名密钥使用安全随机生成器创建一次，内容为 32–4096 字节，权限 0600 或更严，不能是符号链接，且仅运行身份可读。重启继续使用原文件；它与服务访问令牌分开保存，轮换会撤销旧链接。像取件码一样，结果签名只允许取指定的一份文件，不能借它查询其他任务。

接口镜像默认关闭 Uvicorn（网络服务运行器）的访问日志，避免记录签名查询串。覆盖容器启动命令时须保留该设置；代理也不能记录签名或认证头。

容器部署可组合完整基础方案与 `deploy/compose.filetrans.yml`，例如同时指定 `-f deploy/compose.qwen.yml -f deploy/compose.filetrans.yml`，并设置 `SONOVECT_COMPAT_SIGNING_KEY_HOST_FILE` 指向已有密钥。文件须可由容器 UID（用户编号）10001 读取；Compose（容器组合工具）的文件型密钥不会可靠地替你修改宿主文件所有权。覆盖方案会将兼容配置同时传给接口与工作器。反向代理须转发以上四条路径、禁止结果缓存，不记录带签名的输入正文和结果查询参数。公开地址与实际网络仍需部署者单独验收。

## 请求与结果

请求结构与[英文页示例](filetrans-compatibility.md#request-and-result)一致：`model`、`input.file_urls`、`parameters`。仅一份文件、至多一个 `language_hints`（语言提示）、`diarization_enabled`（是否区分说话人），以及 `vocabulary`（词到整数权重的映射）。词条最多 200 个，每条 1–80 字，权重 1–5；权重用于排列模型提示，不能保证识别效果。`vocabulary_id`（预编译词表编号）和未知参数明确拒绝。

建议调用方准备单声道识别副本；立体声混合须沿用调用方现有授权规则。Sonovect 的媒体大小、时长、轨道选择和解码规则继续有效。

提交返回 202 及 `output.task_id`（任务编号），同一幂等请求返回 200 与原编号。状态为 `PENDING`（排队）、`RUNNING`（处理中）、`SUCCEEDED`（成功）、`FAILED`（失败）、`CANCELED`（取消）。成功后读取 `output.results[].transcription_url` 的签名链接。

结果正文为 `transcripts[].sentences[]`：文字、可选的 `begin_time` / `end_time`（起止毫秒）、`speaker_id`（本录音匿名说话人编号）及真实 `words[]`（词和时间）。没有对齐的非空文字可读取，缺失时间保持缺失；不拆字猜时间，不伪造说话人。无文字时以 `ASR_RESPONSE_HAVE_NO_WORDS` 明确失败。模型发现只表明能力声明，不能代替质量验收。

## 安全与恢复

输入只允许 HTTPS 的 443 端口及配置域名，解析出的所有地址都须为公网地址，实际连接固定到已校验地址。拒绝跳转和内网目标，不向输入主机转发服务令牌。下载检查字节数、可用空间及超时，校验摘要后原子保存；签名输入链接仅在私有任务中保存。

可带 `X-Input-SHA256`（识别副本的 SHA-256 摘要）和 `Idempotency-Key`（重复提交识别键），让签名链接续期后仍指向原输入；没有摘要时完整链接也参与请求身份。同一键更换输入、参数、模型或词表返回 409。摘要不符在推理前失败。任务固定接纳时的引擎模型、版本及参数；执行器不匹配时明确失败。

已下载输入在工作器中断后可继续复用；已发布结果在重启后仍为相同字节，原生重跑入口不能覆盖它。确需重新识别时另建任务和请求键。提交结果未知或下载失败先查询原任务，不自动重提。

`SONOVECT_COMPAT_LINK_SECONDS` 默认 3600 秒，且不超过结果保留期；保留期内查询原任务可续发指向相同产物的链接。任务过期查询返回 410，链接失效不会触发识别。`SONOVECT_COMPAT_DOWNLOAD_TIMEOUT` 默认 300 秒；`SONOVECT_COMPAT_MAX_QUEUED` 默认容纳 32 个排队及处理中兼容任务，满载返回 409。

数据库只增量添加兼容字段，旧原生任务编号与成果不变。接口、工作器和配套模型声明须一同升级。回退前停止新准入并排空兼容任务；带前缀的内部状态可防止旧工作器误领地址来源任务，但旧版本无法提供新兼容接口。
