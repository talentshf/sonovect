# 配置与模型选型

Sonovect v0.1.0。部署时选组件，任务时选是否运行；默认任务只转写。配置生成器不安装宿主依赖、不启动服务、不覆盖已有文件；凭据仅写入权限0600的新配置，不打印。

## 推荐组合

| 需求 | 部署选择 | 代价与建议 |
| --- | --- | --- |
| 中文、无显卡起步 | `--route cpu --sound none --voice none` | Paraformer v2.0.4、FSMN、标点、可选CAM++；轻量起点 |
| 多语与显卡推理 | `--route qwen --speech 1.7b` | 推荐Qwen3-ASR、0.6B对齐、CAM++；Qwen默认FireRed VAD |
| 显存较小 | `--speech 0.6b` | 实验性资源折中；既有样本质量弱于1.7B |
| 环境音 | `--sound ast`（配置生成默认） | 独立CPU分类服务，任务另开环境音，不加载MOSS |
| 人声情绪 | `--voice emotion2vec` | CPU实验模型，约1.12GB权重；中文质量未独立验收 |
| 开放式人声描述 | `--voice 4b` / `--voice 8b` | 可选GPU MOSS；更大模型需要更高显存，不保证情绪更准 |
| 音高/能量 | `--measurements` | 无权重CPU服务，可与任意人声后端组合，默认关闭 |

CPU路线支持 `--native-revision v2.0.4|v2.0.9`；后者是配置差异，不代表新训练权重。Qwen可选 `--vad firered|fsmn`。`--sound none|ast`、`--voice none|emotion2vec|4b|8b`独立；同一部署只选择一个人声后端。默认人声和测量均关闭，不再存在隐式联动或第二套分析结构。

## 配置、准备与验收

```sh
sonovect setup --route cpu --sound ast --voice none --measurements --write deploy/.env
# Qwen改为 --route qwen，并使用 deploy/compose.qwen.yml。
docker compose --env-file deploy/.env -f deploy/compose.yml build
python scripts/prepare_deployment.py --compose deploy/compose.yml --plan
python scripts/prepare_deployment.py --compose deploy/compose.yml --check-hardware
docker compose --env-file deploy/.env -f deploy/compose.yml up -d
python scripts/prepare_deployment.py --compose deploy/compose.yml --verify-only --smoke-audio sample.wav
```

`--interactive`提供交互选型；`--write`拒绝覆盖。准备脚本可设 `--env-file`、`--context`，`--plan`只输出计划，`--verify-only`不联网、不写缓存。`--smoke-language`传语言提示。`--check-hardware`先查所选容器的缓存访问、磁盘、内存、显卡容量；健康端点不能代替真实识别。

`sonovect models list`列出固定资产；`models prepare MODEL... --cache DIRECTORY`仅准备所选资产；`models verify MODEL...`离线核对大小和摘要。缺失、损坏、身份不匹配明确失败。正常推理默认离线，仅首次准备需要下载。来源条款作为信息记录，不阻断选型；没有许可确认参数。示例、镜像与源码不打包模型权重。

## 任务与结果

三个严格布尔开关 `analyze_sound`、`analyze_voice`、`measure_voice`均默认false、互相独立。无须选择分析版本。`speakers`默认true，`language`为模型提示，`hotwords`为最多200个、每项1–80字符的提示；`audio_track`默认0，为从零开始的音轨序号。HTTP、CLI与MCP共用同一选项合同，未知字段或字符串布尔值被拒绝。

命令行可用 `--language`、`--no-speakers`、`--analyze-sound`、`--analyze-voice`、`--measure-voice` / `--no-measure-voice`、可重复 `--hotword`、`--audio-track`、`--idempotency-key`、`--wait`。`sonovect wait JOB --timeout SECONDS`等待原任务；`status`、`cancel`、`retry`、`analysis`、`export`均使用相同任务编号。`result --format json|text|srt`读取同一次语音结果；SRT要求一个成功来源且有句级时间。`export`写新目录并校验摘要，不覆盖旧目录。详见[用法](usage.zh-CN.md)和[输出](results.md)。

## 当前默认值与部署内连接

配置生成器默认：`--route qwen --speech 1.7b --vad firered --sound ast --voice none --no-measurements --layout compact`。默认安装3容器，任务仍只转写。下表给出当前部署内连接；完整参数表另外列出独立进程回退值，不能混用。

| 连接/配置 | compact | distributed |
| --- | --- | --- |
| `SONOVECT_PROVIDER_URL` (Qwen) | `http://worker:8080` | `http://speech-provider:8080` |
| `SEGMENTATION_URL` / `QWEN_URL` | `http://127.0.0.1:8082` / `http://127.0.0.1:8081` | `http://speech-segmentation:8082` / `http://speech-asr:8081` |
| `SONOVECT_SOUND_URL` / `EVENTS_URL` | `http://analysis:8084` | `http://speech-events:8084` |
| `SONOVECT_VOICE_URL` / `VOICE_URL` (emotion2vec) | `http://analysis:8085` | `http://speech-vocal:8085` |
| `SONOVECT_VOICE_URL` / `VOICE_URL` (MOSS) | `http://speech-sound:8083` | `http://speech-sound:8083` |
| `SONOVECT_MEASUREMENTS_URL` / `MEASUREMENTS_URL` | `http://analysis:8086` | `http://speech-measurements:8086` |
| `COMPOSE_PROFILES` (AST / CPU vocal / measurements / MOSS) | `analysis` / `analysis` / `analysis` / `voice` | `events` / `vocal-cpu` / `measurements` / `voice` |

## 紧凑部署与分服务部署

`--layout compact|distributed`默认compact（紧凑部署）。CPU与Qwen都以2容器起步；任意AST、emotion2vec、数值组合增加1个CPU分析容器；MOSS独立增加1个显卡容器。配置生成返回`layout`、`compose_file`（配方）、`container_count`（容器数）、准确模型身份和下载体积。配方与生成的功能组须配套。两种布局的任务开关、结果字段完全一致。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `SONOVECT_LAYOUT` | compact | 能力发现中的部署布局：compact、distributed或external，须与配方一致 |
| `SONOVECT_ANALYSIS_TARGET` | analysis-worker | CPU分析构建目标；只选数值时生成analysis-measurements轻量目标 |
| `SONOVECT_ANALYSIS_IMAGE` | sonovect-analysis | 数值专用镜像为sonovect-analysis-measurements，不含模型框架 |
| `ANALYSIS_CPU_LIMIT`, `ANALYSIS_MEMORY_LIMIT` | 2, 6g | 紧凑分析容器的共享处理器/内存上限；各模块仍独立控制线程数 |
| `SEGMENTATION_CACHE`, `SEGMENTATION_HF_HOME` | /models/segmentation, /models/segmentation/huggingface | Qwen切分子进程的ModelScope/Hugging Face模型缓存，与识别缓存分开 |
| `QWEN_HF_HOME` | /models/qwen/huggingface | 紧凑语音容器中Qwen识别与对齐的模型缓存 |

紧凑部署的AST、人声CPU与测量分别使用`http://analysis:8084`、`http://analysis:8085`、`http://analysis:8086`；MOSS继续使用`http://speech-sound:8083`。接口连接`http://worker:8080`；语音容器内部协调、切分8082与识别8081通过回环地址互通。`COMPOSE_PROFILES`（功能组）只转写时为空，CPU分析为`analysis`，仅MOSS为`voice`，两者都选为`analysis,voice`。高级分服务部署保留events/vocal-cpu/measurements/voice功能组，完整表中的分服务地址是独立进程回退值。`MEASUREMENTS_CPU_LIMIT`与`MEASUREMENTS_MEMORY_LIMIT`仅作用于分服务配方；紧凑布局使用共享分析上限。各模型根目录仍可独立配置。未启用的进程不启动，权重仍按任务需求加载；准备阶段只下载选中的模型，正常运行保持离线。

`--no-measurements`明确关闭部署中的数值测量，与默认值相同；`--measurements`开启此能力。两者都不会改变任务级`measure_voice`（是否执行测量）的独立开关。

## 资源与参数完整表

显存预算只限制模型分配器，不等于进程总显存；同卡多服务要保留余量。提高超时不提高速度。分段、阈值、窗口会改变质量与代价，先用自有代表素材比较。数值服务的 `MEASUREMENT_THREADS`、`MEASUREMENT_WINDOW_SECONDS`和容器限额独立于情绪窗口；无语音不编造数值。

| 参数 | 默认 | 作用与调整 |
| --- | --- | --- |
| `SONOVECT_TOKEN` / `SONOVECT_TOKEN_FILE` | 必填，二选一 | 非占位令牌或明确的受限文件；不得同时设置。不要提交到版本库 |
| `SONOVECT_URL` | `http://127.0.0.1:8096` | 客户端连接地址；跨不可信网络应通过 HTTPS（加密传输）入口 |
| `SONOVECT_MCP_INPUT_ROOT` | 未设置，禁止提交 | MCP进程可读的绝对目录；解析符号链接后仍须在此目录内 |
| `SONOVECT_PROJECT`、`SONOVECT_VERSION`、`SONOVECT_REVISION` | `sonovect`、当前版本、`uncommitted` | Compose项目名、镜像版本和来源提交；验收与恢复应固定实际镜像摘要 |
| `SONOVECT_BIND`、`SONOVECT_PORT` | `127.0.0.1`、`8096` | 监听地址与空闲端口；变更前确认端口占用 |
| `SONOVECT_DATA_DIR` | `./data/jobs`，容器`/data` | 工作进程可写的持久目录 |
| `SONOVECT_BACKEND` | `funasr` | `funasr`或`speech`；由选用的Compose路线固定 |
| `SONOVECT_MODEL` / `SONOVECT_MODEL_REVISION` | `paraformer-zh` / `v2.0.4` | 当前原生模型清单支持的固定组合；其他模型需新增适配和验收 |
| `SONOVECT_DEVICE` | `cpu` | 原生设备；自配GPU需对应镜像、设备权限和实测 |
| `SONOVECT_PROVIDER_URL` | `http://speech-provider:8080` | 兼容私有协调器地址 |
| `SONOVECT_SOUND_ENABLED`、`SONOVECT_SOUND_URL` | 独立核心true、配方false；空 | AST能力开关与原生AST服务地址；生成器选择ast后启用 |
| `SONOVECT_PROVIDER_TIMEOUT` | `7200`秒 | 正数，覆盖一次模型处理；加大不会提高性能 |
| `SONOVECT_MAX_UPLOAD_BYTES` / `SONOVECT_MAX_FILES` | `268435456` / `16` | 正整数，每个任务聚合体积/文件数；不等于解码后内存上限 |
| `SONOVECT_MAX_MEDIA_SECONDS` / `SONOVECT_MEDIA_TIMEOUT` | `7200` / `300`秒 | 正数，每个来源的解码时长和解码耗时上限 |
| `SONOVECT_INPUT_TTL_HOURS` / `SONOVECT_RESULT_TTL_HOURS` | `24` / `168`小时 | 正数，任务终态起保留期限；需要重试时输入必须仍存在 |
| `SONOVECT_LEASE_SECONDS` / `SONOVECT_POLL_SECONDS` | `120` / `0.1`秒 | 正数，任务租约和空闲轮询间隔；运行中续租，崩溃后到期可接管 |
| `SONOVECT_WORKER_STALE_SECONDS` / `SONOVECT_WORKER_HEALTH_FILE` | `45`秒 / `/tmp/sonovect-worker.json` | 正数心跳阈值；同宿主独立进程使用不同健康文件 |
| `SONOVECT_MODELS_OFFLINE` | `1`（生成配置/运行配方） | `1`禁止启动时下载；`0`显式允许按清单准备。CPU映射到`MODELSCOPE_OFFLINE` |
| `MODELSCOPE_CACHE` / `HF_HOME` | 角色镜像`/models`下 | SDK缓存路径；配方卷分别隔离，不能只搬一个权重文件 |
| `SONOVECT_ENV_FILE`、`SONOVECT_PROCESSING_NETWORK` | `.env`、`sonovect_default` | 外部模型网络配方的受限配置和现有网络名 |
| `SONOVECT_IMAGE`、`SONOVECT_WORKER_IMAGE` | 当前核心/媒体工作镜像 | 外部网络配方覆盖镜像名；生产应固定已验收摘要 |
| `QWEN_GPU_BUDGET_MIB` / `MOSS_GPU_BUDGET_MIB` | `8192` / `12288` | 正整数，PyTorch分配器上限；8B生成配置为19456。预算加预留必须小于等于实际设备容量，加载时空闲也须满足；不是物理隔离或总进程硬上限 |
| `GPU_RESERVE_MIB` | `1024` | 至少512，为分配器外开销和设备预留空间；共享GPU还应给其他应用留出余量 |
| `QWEN_MIN_FREE_GIB` / `MOSS_MIN_FREE_GIB` | `6` / `10` | 非负数；加载门槛取本项和“预算+预留”的较大值。8B配置20。只改门槛不会扩大分配器预算 |
| `GPU_CAPACITY_WAIT_SECONDS` | `360` | 非负秒，等待其他任务释放显存的最长时间；0立即失败 |
| `QWEN_DEVICE` / `MOSS_DEVICE` | `cuda:0` | 当前GPU路线在指定设备运行；CPU自配不等于本配方通过容量验收 |
| `QWEN_DTYPE` | `bfloat16` | `bfloat16`、`float16`或`float32`；后者显存增加，兼容性/质量需重测。MOSS按固定权重配置`auto`，未提供量化开关 |
| `QWEN_ATTENTION_IMPLEMENTATION` | `auto` | `auto`、`sdpa`、`eager`；其他后端未打包，不能仅改名称启用 |
| `QWEN_IDLE_UNLOAD_SECONDS` / `MOSS_IDLE_UNLOAD_SECONDS` | `300` | 正整数秒，无任务空闲卸载；小值省常驻显存但增加冷启动 |
| `MOSS_UNLOAD_AFTER_REQUEST` | `true` | `true`/`false`；默认每请求释放，改为false增加驻留显存；协调器会在下一次ASR前确认释放 |
| `QWEN_ASR_MODEL` / `QWEN_ASR_REVISION` | 清单1.7B固定组合 | 可切0.6B固定组合；必须一并修改并准备缓存 |
| `QWEN_ALIGNER_MODEL` / `QWEN_ALIGNER_REVISION` | 清单0.6B对齐固定组合 | 当前唯一已实现对齐模型；不支持用ASR权重代替 |
| `MOSS_AUDIO_MODEL` / `MOSS_AUDIO_REVISION` | 清单4B固定组合 | 可切实验8B组合，同时调整预算并实测 |
| `MOSS_MODEL_ROOT` | 空 | 容器内的高级独立快照目录，须通过卷挂载且与模型清单逐文件匹配；不接受自写校验回执绕过 |
| `SEGMENT_TARGET_MS` / `SEGMENT_HARD_MAX_MS` | `30000` / `90000` | 正整数，目标/基础语音区间的硬上限，前后余量另加、合计最多`2*SEGMENT_PADDING_MS`；目标不得超过硬上限；短窗口减少单次显存，可能损失上下文 |
| `SEGMENT_MERGE_GAP_MS` / `SEGMENT_BOUNDARY_SILENCE_MS` | `3000` / `700` | 非负整数，合并间隔和可用静音边界；调整会改变切句 |
| `SEGMENT_PADDING_MS` | `1000` | 非负整数，切段前后余量；过大可能重复上下文 |
| `MIN_TEXT_DENSITY_PER_SPEECH_SECOND` | `0.2` | 非负数，每语音秒最低文字密度，产生质量提示 |
| `SONOVECT_VAD_BACKEND` | 配方`firered` | `firered`或`fsmn`，映射提供者`VAD_BACKEND`（独立启动默认fsmn） |
| `VAD_MODEL` / `SPEAKER_MODEL` | `fsmn-vad` / `cam++` | 当前固定别名；FireRed不加载FSMN；说话人模型仍参与Qwen内部处理 |
| `FIRERED_VAD_ROOT` | 空 | 独立启动时可指定已校验目录；配方自动从固定快照解析 |
| `SEGMENTATION_DEVICE` | `cpu` | 现有分段镜像使用CPU框架；改cuda不会自动安装显卡框架 |
| `SPEAKER_MERGE_THRESHOLD` | `0.78` | 0–1，CAM++聚类合并阈值，调整可能改变人数 |
| `SPEAKER_LOW_COHESION_COSINE` | `0.45` | -1–1，单簇低一致性保守回退门槛 |
| `SPEAKER_FALLBACK_MIN_WINDOWS` / `SPEAKER_FALLBACK_COUNT` | `20` / `2` | 正整数，回退所需窗口数和回退人数；不是任务指定真实人数 |
| `MIN_SPEAKER_PROFILE_DURATION_MS` | `5000` | 非负整数毫秒，内部说话人特征档的最低时长，不建立跨录音身份库 |
| `QWEN_MAX_BATCH_SIZE` / `QWEN_MAX_BATCH_AUDIO_SECONDS` | `1` / `60` | 1–4的整数/正数，批量数量与合批音频秒数上限；单段超过秒数时仍单独处理，切段上限由`SEGMENT_HARD_MAX_MS`控制。增大可能加速也可能溢出显存，默认1保守运行 |
| `QWEN_MAX_NEW_TOKENS` | `2048` | 正整数，每个ASR生成段的长度上限；太小截断，太大延迟/显存增加；贪心解码，未开放随机温度 |
| `QWEN_DEFAULT_CONTEXT` | 空 | 部署级专名提示；不应存个人词库或用户秘密。与任务hotwords区别是全局生效 |
| `QWEN_ROLLING_CONTEXT_CHARS` | `0` | 非负整数，前段文字上下文长度；0关闭，开大可能重复或传播前段误识别 |
| `MOSS_MAX_CHUNK_SECONDS` | `90` | 正整数，最大声音分析窗口；越长特征、生成和显存开销越大 |
| `MOSS_STRUCTURED_RETRIES` | `2` | 非负整数，结构化输出重试次数；不能把多次结果挑成最好一次来评测 |
| `MOSS_MAX_NEW_TOKENS` | `768` | 正整数，每个声音分析窗口的输出长度；过小导致JSON截断，增加不代表准确率提高 |
| `MOSS_DEBUG_RAW` | `false` | `true`/`false`，诊断原始模型内容；可能含媒体信息，默认关闭且不要公开日志 |
| `SEGMENTATION_TIMEOUT_SECONDS` / `QWEN_TIMEOUT_SECONDS` / `MOSS_TIMEOUT_SECONDS` | `600` / `1800` / `3600` | 正秒，提供者内部各阶段超时；与核心提供者总超时协调 |
| `SEGMENTATION_URL` / `QWEN_URL` / `MOSS_URL` | 镜像默认内部工作进程地址 | 配方固定为当前服务名；提供者端口不公开 |
| `SOUND_ENABLED` | 独立提供者`false` | 配方映射`SONOVECT_SOUND_ENABLED`；不要让核心与提供者开关不一致 |
| `SONOVECT_VOICE_ENABLED` / `SONOVECT_VOICE_URL` | false / `http://speech-sound:8083`（配方） | 独立MOSS能力与原生路线地址 |
| `SOUND_ENABLED` / `VOICE_ENABLED` | false / false | 协调器与核心匹配的两个能力开关 |
| `EVENTS_URL` / `EVENTS_TIMEOUT_SECONDS` | `http://speech-events:8084` / 600秒 | 协调器AST连接与正数超时 |
| `COMPOSE_PROFILES` | 生成器`analysis`；只转写为空；MOSS增加`voice` | 匹配独立服务；改变开关须同时改变对应服务 |
| `SOUND_EVENT_MODEL_ROOT` | 未设置 | 容器内的已校验AST目录；显式挂载避免重复下载 |
| `SOUND_EVENT_THRESHOLD` | 0.1 / [0,1] | 提高减少弱标签，也增加漏报；不是准确概率 |
| `SOUND_EVENT_TOP_K` | 5 / 整数1–10 | 每10秒窗口最多标签数；父子标签可能描述同一声源 |
| `SOUND_EVENT_WINDOW_SECONDS` | 10 / [1,10]秒 | 缩短提高时间粒度和计算量，不是精确起止 |
| `SOUND_EVENT_THREADS` | 2 / 整数1–32 | CPU分类线程，过多可能争抢转写资源 |
| `SONOVECT_MEASUREMENTS_ENABLED` | false | 接口与工作器能力，需与协调器一致 |
| `SONOVECT_MEASUREMENTS_URL` | 生成配置使用内部服务地址 | 原生路线测量接口 |
| `MEASUREMENTS_ENABLED` / `MEASUREMENTS_URL` | false / `http://speech-measurements:8086` | 协调器测量能力与地址 |
| `MEASUREMENTS_TIMEOUT_SECONDS` | 600秒 | 协调器测量阶段超时 |
| `MEASUREMENT_THREADS` | 2 | 处理器与数值编译线程，1–32 |
| `MEASUREMENT_WINDOW_SECONDS` | 10秒 | 真实测量窗口，1–30秒；独立于 `VOCAL_WINDOW_SECONDS` |
| `MEASUREMENTS_CPU_LIMIT` / `MEASUREMENTS_MEMORY_LIMIT` | 2 / 2g | 容器处理器与内存上限 |
| `SONOVECT_VOICE_BACKEND` / 协调器 `VOICE_BACKEND` | `moss`；可选 `moss`、`emotion2vec` | 部署级后端，setup 自动保持一致 |
| `SONOVECT_VOICE_URL` / 协调器 `VOICE_URL` | MOSS为`http://speech-sound:8083`；紧凑CPU为`http://analysis:8085`；分服务CPU为`http://speech-vocal:8085` | 私有服务地址，任务不能任意指定 |
| `VOCAL_MODEL_ROOT` | 空 | 容器内固定且摘要校验通过的权重目录 |
| `HF_HUB_CACHE` | SDK（软件开发库）默认，位于 `HF_HOME` 下 | 沿用原生缓存覆盖项，不建立第二套缓存登记 |
| `VOCAL_THREADS` | 2，整数 1–32 | 推理线程；配方分配两个 CPU |
| `VOCAL_WINDOW_SECONDS` | 10 秒，范围 1–30 秒 | 不重叠的分析窗口；改小会增加开销并改变上下文，需要重新评测 |

[部署路线](deployment-options.md) · [组件来源](model-licenses.md) · [安全边界](../SECURITY.md)

`sonovect --version` 显示产品版本；`sonovect ready` 检查服务就绪状态，不加载模型。

准备模式在任何下载前先逐文件校验缓存摘要，按底层文件系统合计实际缺失量，加一份最大缺失文件暂存量和1GiB余量；不足即失败。完整缓存不要求新增下载空间；显式模型目录先校验且不重复下载。`--verify-only`不要求写入容量；`--plan`仅给出与目录无关的选型概览；`sonovect models plan MODEL... --cache DIRECTORY`只读检查当前缓存。其他进程占盘仍会改变剩余容量。

## 环境音时间窗与长录音

AST特征提取至少需要25毫秒信号帧。录音最后不足25毫秒的片段仅在特征输入上补零，输出时间仍使用原媒体的实际整数毫秒边界；舍入后没有有效时长的亚毫秒片段不生成观察。短尾片不会再使此前有效窗口一起失败，这不代表模型能够准确辨别任意微小声音。

环境音在CPU上按窗口处理，长录音耗时随窗口数量增长。结合本机实测协调`EVENTS_TIMEOUT_SECONDS`与总处理超时；缩短窗口也会增加计算量。阈值与窗口比较的语料范围见[质量协议](quality-protocol.md)，分数不是校准后的准确概率。

## 共享显卡加载与诊断

Qwen和MOSS先核验选定固定版本的模型文件，再在模型实际分配显存前检查当前余量。大型权重的摘要校验可能耗时几十秒，期间其他服务可以加载模型，提前读取的空闲值会失效。加载门槛取“最小空闲”与“分配器预算加预留”的较大值；8B选型为19456MiB预算、20GiB最小空闲。`GPU_CAPACITY_WAIT_SECONDS`限制校验后的等待时间；冷启动等待应与暖机推理延迟分开计量。

准入检查读取当前余量，其他独立进程随后仍可能分配显存。共享显卡上的常规评测和验收应串行；专门做并发实验时记录其他消费者及时间线。可选人声阶段失败时保留有效语音和其他分析，容量恢复后可重试同一任务。提高分配器预算不会增加物理显存。

MOSS运行异常记录错误类型和格式化调用栈，结构无效时记录JSON（结构化数据）/人声结构原因、尝试次数及字符数；原生适配器记录可选阶段与上游状态码。默认不记录音频字节或模型生成描述。`MOSS_DEBUG_RAW=true`显式在内部响应中启用原始描述，仅用于适合纳入受控诊断存储的素材。清理CUDA（显卡计算运行时）前解除异常对调用栈对象的引用，使部分加载的模型可以释放。

SQLite（嵌入式数据库）的临时写锁冲突会让工作进程等待后重试，避免退出整个处理单元。空闲队列和状态轮询避免无事可做时反复取得写锁；清理与任务领取在写锁内重新核对期限和归属。写锁冲突重试至少等待100毫秒，正常空闲轮询仍按`SONOVECT_POLL_SECONDS`。永久存储错误仍使工作进程停止；输入/结果保留期、取消和同任务重试的期限沿用原规则。

中文情绪的新一轮同素材比较仍未通过稳定标准；默认保留`--voice none`。FireRed加base的480条测试严格命中率为45%，100条自然非语音对照仍有14条情绪输出。更大模型和更短窗口都不保证改善，详见[质量与选型](quality.zh-CN.md)。稳定数值需求应单独开启音高能量，无需情绪权重。
