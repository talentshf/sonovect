# 组件来源与声明

Sonovect是模型组装与服务平台，负责接入、任务、输出和部署；模型由部署者显式选型、按需准备。以下信息保留上游身份与发布声明，不作为功能准入门槛，平台不替上游向所有用户提供统一授权。Sonovect自有代码为Apache-2.0；各组件原有声明分别保留。

| 选项 | 模型来源与固定修订 | 发布声明 |
| --- | --- | --- |
| `qwen-1.7b` | [Qwen/Qwen3-ASR-1.7B-hf](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf/tree/bcd2b5b7f32b480ab5790554cfa8347f246a14f3) · `bcd2b5b7f32b480ab5790554cfa8347f246a14f3` | Apache-2.0 |
| `qwen-0.6b` | [Qwen/Qwen3-ASR-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf/tree/7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c) · `7f1569a48a89f3e3f4dc3a5c9d28bddd903bc76c` | Apache-2.0 |
| `aligner` | [Qwen/Qwen3-ForcedAligner-0.6B-hf](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf/tree/c07281df297b9905d24a508279258cccf987a064) · `c07281df297b9905d24a508279258cccf987a064` | Apache-2.0 |
| `moss-4b` | [OpenMOSS-Team/MOSS-Audio-4B-Instruct](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-4B-Instruct/tree/6907a499dc0e87cc77c8ae0fe23fd0eb5476a02d) · `6907a499dc0e87cc77c8ae0fe23fd0eb5476a02d` | Apache-2.0 |
| `moss-8b` | [OpenMOSS-Team/MOSS-Audio-8B-Instruct](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-8B-Instruct/tree/d4dc5a6d8cd79b43dcd82884c75e303b1ecd016d) · `d4dc5a6d8cd79b43dcd82884c75e303b1ecd016d` | Apache-2.0 |
| `firered` | [FireRedTeam/FireRedVAD](https://huggingface.co/FireRedTeam/FireRedVAD/tree/7990aaccc6b7aec1e527743bd30201f2c4a03b8c) · `7990aaccc6b7aec1e527743bd30201f2c4a03b8c` | Apache-2.0 |
| `paraformer` | [iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch](https://www.modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) · `v2.0.4` | Apache-2.0 |
| `fsmn` | [iic/speech_fsmn_vad_zh-cn-16k-common-pytorch](https://www.modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch) · `v2.0.4` | Apache-2.0 |
| `punc` | [iic/punc_ct-transformer_cn-en-common-vocab471067-large](https://www.modelscope.cn/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large) · `v2.0.4` | Apache-2.0 |
| `cam` | [iic/speech_campplus_sv_zh-cn_16k-common](https://www.modelscope.cn/models/iic/speech_campplus_sv_zh-cn_16k-common) · `v2.0.2` | Apache-2.0 |
| `paraformer-v2.0.9` | [iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch](https://www.modelscope.cn/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch) · `v2.0.9` | Apache-2.0 |
| `ast-events` | [MIT/ast-finetuned-audioset-10-10-0.4593](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593/tree/f826b80d28226b62986cc218e5cec390b1096902) · `f826b80d28226b62986cc218e5cec390b1096902` | BSD-3-Clause |
| `emotion2vec-base` | [emotion2vec/emotion2vec_plus_base](https://huggingface.co/emotion2vec/emotion2vec_plus_base/tree/b318240bfe67db81a8c572ecb37ce9c3759b81c9) · `b318240bfe67db81a8c572ecb37ce9c3759b81c9` | model-license |

emotion2vec两个官方来源声明不同，当前固定资产仍照实保留原声明。MOSS固定代码树缺少其元数据引用的许可正文，派生包保留该事实与对应源码，不自行补造上游授权。这两项均保留实验接入，不设置强制确认或等待询证；中文情绪保持实验功能，已有表演语料结果不代表自然对话准确率。

源码、Python安装包和维护镜像不携带模型权重。首次准备直接从固定官方来源下载，运行前校验文件摘要。修改系统库、FFmpeg及其他依赖的对应源码、构建说明和声明保留在镜像中，详见[第三方说明](../THIRD_PARTY_NOTICES.md)。
