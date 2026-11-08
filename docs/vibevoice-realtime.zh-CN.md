# VibeVoice 文件转写与可选实时识别

以下扩展均为可选的未发行能力。默认文件任务、原任务编号查询和恢复方式保持；代码测试不能替代模型质量、显存和部署验收。[英文完整合同](vibevoice-realtime.md)提供对应上游链接。

## VibeVoice 文件路线

新增 `sonovect setup --route vibevoice --write deploy/.env.vibevoice`，选择 `deploy/compose.vibevoice.yml`。Sonovect（声音处理服务）通过微软官方 vLLM（模型推理服务框架）的 `/v1/chat/completions` 接口，发送音频和热词，读取文字、句段时间及匿名说话人。

需要先准备私有上游服务，设置 `SONOVECT_PROVIDER_URL` 为其根地址，不带 `/v1`；服务模型名默认为 `vibevoice`，选定权重修订为 `d0c9efdb8d614685062c04425d91e01b6f37d944`。上游应保持私网访问；如已启用密钥认证，设置 `SONOVECT_PROVIDER_TOKEN_FILE` 指向其原生受限密钥文件，并在两个核心容器中只读挂载。不要把凭据放入网址，Sonovect 自身仍使用现有令牌认证。任务记录中的修订来自管理员配置；模型列表只能核实服务名称，真实加载修订必须单独回读。

生成器不会下载模型或启动服务。两个 Sonovect 容器之外，还需要外部显卡推理服务；原版权重约 17.35GB。Compose（容器编排）必须显式设置从本候选源码构建的 `SONOVECT_IMAGE` 和 `SONOVECT_WORKER_IMAGE`，旧 v0.2.0 镜像不含新代码。配置解析示例：

```sh
SONOVECT_ENV_FILE=.env.vibevoice docker compose --env-file deploy/.env.vibevoice -f deploy/compose.vibevoice.yml config --quiet
```

默认每文件最多 900 秒。超过上限明确失败，不自动切成多个各自编号的说话人空间。24GiB 显卡只作为短录音验证目标；32GiB 留有更多余量，长录音或并发可评估 48/80GiB 级别。这些是容量规划建议，尚无本机实测；注意力计算方式、输出长度和并发都会改变峰值，不能保证一小时整段能跑。

仍使用现有持久文件任务、字幕与导出接口。秒转换成整数毫秒，说话人仅在当前录音内匿名编号；句段时间不补造成字词时间。无效返回、截断输出、越界时间明确失败，读取结果不会重复推理。该路线暂不支持环境音、情绪及数值测量，请求时拒绝而不静默忽略。使用独立项目名、任务卷和显式消费者连接，不让不同识别后端领取同一队列，也不改变 Sayflit 默认连接。

## Qwen 实时路线

现有文件工作器使用 Transformers 5（模型框架）与 `-hf` 权重；官方实时 SDK（开发包）`qwen-asr==0.0.6` 需要 vLLM 0.14.0、Transformers 4.57.6，不能原地安装或降低现役依赖版本。实时服务使用独立显卡进程，先复用兼容共享环境；确实不兼容时才准备隔离环境。依赖在 `providers/realtime/requirements.txt`，还需安装同一选定 Sonovect 包及其核心依赖，并通过 `python -m pip check`。这些依赖及镜像尚需独立安全和显卡验收。

使用本地、固定修订的 SDK 格式 `Qwen/Qwen3-ASR-1.7B` 目录，不能直接替换为现有文件工作器的 `-hf` 目录。模型和缓存遵循原部署存储政策。通过原生受限令牌文件设置 `SONOVECT_TOKEN_FILE`，并设置：

- `SONOVECT_REALTIME_ENABLED=true`
- `SONOVECT_REALTIME_MODEL_PATH=<本地SDK模型目录>`
- `SONOVECT_REALTIME_GPU_MEMORY_UTILIZATION=0.35`（默认显存预分配比例）

在已准备的显卡运行时启动：

```sh
uvicorn sonovect.realtime:create_realtime_app --factory --host 127.0.0.1 --port 8097 --workers 1 --ws-max-size 64000 --no-server-header
```

只能运行一个服务进程，并发限制在进程内生效。独立服务提供 `/health`、需要认证的 `/v1/capabilities` 和 `/v1/realtime`，不创建文件队列。健康返回只代表进程存活和模型是否加载，不能当作推理就绪。模型首次授权调用时加载，公开服务前仍需真实推理验证。主 API（网络接口）也注册了这条实时端点，但默认关闭；独立服务需要客户端显式连接其地址，主服务不会假称已接入外部实时服务。

24GiB 单卡不要同时运行 VibeVoice 与实时模型。实时模型预留显存后不会随每个会话自动卸载；切换显卡用途按部署流程执行，本实现不自动停止现役模型。

## 命令行与会话合同

客户端安装可选 `stream-client` 依赖，沿现有机制设置 `SONOVECT_URL` 和令牌文件：

```sh
sonovect stream mono-16khz-pcm16.wav --language Chinese --hotword Sonovect
sonovect stream --stdin --language Chinese
```

WAV（音频容器）需为单声道、16kHz、16位整数无压缩音频，用于测试流式协议；该命令不自动打开麦克风。`--stdin` 接收录音软件持续传入的 PCM（原始音频采样），格式为单声道、16kHz、小端有符号16位。录音软件负责保存原录音，便于后续需要时明确提交文件对齐与分说话人。

WebSocket（双向连接）地址为 `/v1/realtime`，令牌仅通过 `Authorization`（认证头）传入，不接受网址查询参数。浏览器直接使用长期服务令牌的入口未提供。

1. 发送 `{"type":"start","sample_rate":16000,"encoding":"pcm_s16le","language":"Chinese","hotwords":["Sonovect"]}`，等待 `started`。
2. 发送二进制音频帧，每帧非空、偶数字节、最多64000字节（两秒）；收到对应 `partial`（草稿）再发送下一帧，避免无限积压。
3. `partial.text` 是完整草稿，每次**替换前一版**，不能追加；模型可能改写前面的词。`session_id`（会话编号）内的 `sequence`（序号）递增。`received_audio_ms` 仅代表已接收采样时长，不是文字对齐时间。
4. 发送 `{"type":"finish"}` 冲刷最后不足两秒的尾音，收到 `final`（定稿）才算完成。错误终止时，客户端保留上一版未完成草稿，不自动重连或重新提交。

输出为 NDJSON（每行一个结构化对象），每条及时刷新。默认限制：每进程一个会话、最多300秒音频、30秒空闲。第二个调用者收到 `realtime_busy`。连接断开后放弃会话，不自动生成定稿、不转成文件任务；仍在计算的模型结束后才释放运行名额。

实时会话暂不持久化、不支持断点恢复，草稿与定稿由客户端保存；这与文件任务的持久恢复合同分别声明。官方 SDK 会重新输入累计音频，并利用前缀回退修订文字，不能承诺恒定延迟或增量缓存。Qwen 路线只提供实时文字，不提供实时字词时间、说话人或附加声音分析。本轮不增加 Sayflit 页面；新增 VibeVoice 1.5B 流式路线见下文。

本地测试使用合成音频和注入的固定返回，验证鉴权、处理结束前出字、草稿替换、尾音、容量边界、断线和同文件任务取回。它们不证明真实识别质量、显存峰值、冷启动、完整时长、并发性能、镜像安全或上线成功。

## 新增 VibeVoice Streaming 1.5B（流式小版）

选定 `microsoft/VibeVoice-ASR-Streaming-1.5B` 的固定修订 `4262d23d8a539a6530cf64fbd0b1751ef9a30853`。所需完整文件共5,644,393,692字节，其中权重约5.63GB；模型清单记录每个文件的大小和摘要。这与上面的原版离线模型分别准备，不能互换目录。

本路线作为默认 Qwen 文件服务的**备选，按需运行，不常驻部署**，也未包含在 v0.2.0 正式发行中。独立容器设置 `restart: 'no'`（不自动重启），用前台临时容器运行，退出后删除。模型会在进程内跨会话保留，需要停止进程才能释放显存。

```sh
sonovect setup --route vibevoice-1.5b --write deploy/.env.vibevoice-15
sonovect models prepare vibevoice-stream-1.5b --cache <管理员选定的模型缓存>
```

官方推理代码固定在 `providers/realtime/requirements.vibevoice.txt` 声明的提交；其 Transformers（模型框架）版本要求低于5，因此也需要独立运行环境，不降低现役文件工作器的依赖。兼容的 Torch/CUDA（张量计算与显卡运行时）、认证和模型缓存继续复用。核心客户端不会自动安装显卡开发包。

`deploy/compose.realtime.vibevoice.yml` 使用一个独立容器，不挂文件任务卷。`SONOVECT_REALTIME_IMAGE` 必须显式选择带本次 Sonovect 源码及已验证依赖的镜像；`SONOVECT_MODELS_DIR` 指向包含 `huggingface/` 的模型根目录，启动后只读挂载，按生成配置定位固定快照。文件缺失或摘要不符会在加载前拒绝，正常推理保持离线。

选定已验证镜像、准备私有配置、模型和现有认证后，只启动本服务：

```sh
SONOVECT_ENV_FILE=.env.vibevoice-15 docker compose --env-file deploy/.env.vibevoice-15 -f deploy/compose.realtime.vibevoice.yml run --rm --service-ports --name sonovect-vibevoice-on-demand realtime
```

用完按 Ctrl+C 退出；从其他终端停止时，执行 `docker stop sonovect-vibevoice-on-demand`，确认临时容器退出后再安排其他显卡任务。不将此配方加入默认文件服务的启动流程。生成配置和准备模型不会启动服务或切换现有调用方。

源码运行也可设置 `SONOVECT_REALTIME_BACKEND=vibevoice-1.5b`、`SONOVECT_REALTIME_MODEL_PATH=<本地固定快照目录>`，显式启用实时服务，沿用前文启动命令。`SONOVECT_REALTIME_DEVICE` 默认 `cuda:0`（BF16，16位浮点），也支持 `cpu`（FP32，32位浮点）做功能检查，处理器不保证实时速度。加载前检查空闲显存是否覆盖分配器预算及1GiB余量；默认预算仍为 `SONOVECT_REALTIME_GPU_MEMORY_UTILIZATION=0.35`。这限制本进程的张量分配器，不是整卡预留，也不是容量或速度保证。

客户端仍输入16kHz音频。每个会话通过独立的 SoXR（重采样库）状态连续转换成24kHz，结束时冲刷滤波尾音。模型每次读取2.933秒的推进块及0.533秒前看音频，只消费推进块，保留前看部分；最后不足一块的真实尾音补零处理，不重复识别已消费音频。模型内部上下文仅留在当前会话。默认上限300秒，配置不得超过官方发布权重的480秒范围。

`partial.text` 和 `final.text` 保留完整模型文字，包括原生说话人标签。可选 `speaker_segments`（说话人文字段）只从模型实际输出的 `Speaker N:` 标签解析会话内匿名编号；没有标签就不造身份。片段没有时间戳，接收采样数量或模型切块边界不能冒充句段、字词对齐。命令行仍用前文 WAV 或实时标准输入命令，模型由服务端选定，能力查询会声明所选路线和说话人支持。

`scripts/qualify_vibevoice_stream.py` 用两段公开的 Qwen 中英文样例，经真实模型、服务和命令行进行短测，记录张量分配器显存峰值及原生说话人文字。只在独立测试环境运行，使用新结果目录，完成回执会阻止重做已完成批次。短样例不代表中文会议准确率、分人准确率、八分钟稳定性、冷暖机统计或生产镜像验收。

2026-11-09 在隔离的 RTX3090／24GiB 环境完成真实模型、服务及命令行短测。15.051秒英文样例在定稿前返回草稿，进程的 PyTorch（张量框架）分配峰值5004.9MiB、预留峰值5262MiB（约5.14GiB），不含其他显卡分配。4.204秒中文样例复用已成功事件，没有留存耗时或显存；定稿开头为“山治”，[官方样例参考](https://github.com/QwenLM/Qwen3-ASR/blob/main/examples/example_qwen3_forced_aligner.py)为“甚至”。这说明接入跑通，也存在误识别，继续保留 Qwen 默认路线。短测不代表麦克风延迟、长会话、多人准确率或生产镜像验收。

实测使用的精简镜像没有C编译器，PyTorch 2.14的新算子即时编译会因此失败。配方只在可选实时容器设置官方原生控制 `TORCH_DISABLE_NATIVE_JIT=1`，走已有非即时编译路径，不修改框架源码。有完整编译工具链的镜像可覆盖此值后另测性能。验证工具保留公开原音频，对其他采样率/位深用现有FFmpeg转换；后一条样例失败后复用已完成事件，不编造前一条丢失的耗时或显存测量。
