# Contributing / 参与贡献

[English](#english) · [中文](#中文)

## English

Sonovect welcomes first-time contributors and users running local ASR on different hardware. You can help without training a model or writing a new backend.

| Start with | Useful contribution |
| --- | --- |
| Documentation | Reproduce a setup step, clarify a parameter, improve an example or translation |
| Deployment experience | Share the release, OS, CPU/GPU, selected route, startup time and a reproducible configuration with secrets removed |
| Quality or performance | Compare public or consented reference material; report model/configuration, sample counts, scoring and cold/warm timing separately |
| Code | Fix a reproducible bug, improve a supported integration or add a focused regression test |

Use [Discussions](https://github.com/talentshf/sonovect/discussions) for questions, deployment experiences and ideas. Use [Issues](https://github.com/talentshf/sonovect/issues/new/choose) for reproducible bugs or concrete proposals. Small fixes and documentation improvements can go straight to a pull request. For larger changes, describe the problem and scope first so contributors can coordinate before investing substantial work.

Describe the user-visible problem and a minimal reproduction using synthetic or openly licensed audio. Do not attach credentials, private recordings/transcripts, internal URLs, model weights or personal speaker templates. Report security issues privately using [SECURITY.md](SECURITY.md).

Fork the repository, create a topic branch and keep each pull request focused. Explain what changes for the user and how you checked it. Documentation-only changes need link/example review; code changes should run the relevant checks below. Keep English and Chinese explanations aligned where both exist. No separate contributor agreement is required; contributions use this repository's Apache-2.0 license. Preserve upstream copyright and license notices.

## 中文

欢迎第一次参与开源的贡献者，也欢迎在不同硬件上部署本地语音识别的使用者。不必先训练模型或开发完整后端，小的修正同样有价值。

- **文档：** 实际走一遍部署步骤，解释不清楚的参数，完善示例与中英翻译。
- **部署经验：** 提供版本、系统、CPU（处理器）/GPU（显卡）、路线、启动时间及去除凭据后的可复现配置。
- **质量与性能：** 使用公开或获准的参考素材，说明模型、配置、样本数、评分规则，并分别记录首次运行和暖机后的延迟。
- **代码：** 修复可复现问题、改进已有接入方式、补充能捕获真实问题的回归测试。

使用问题、部署经验和想法进入[讨论区](https://github.com/talentshf/sonovect/discussions)；明确的缺陷或功能提议进入[问题区](https://github.com/talentshf/sonovect/issues/new/choose)。小修复和文档改进可直接提交 PR（合并请求）；较大的变更先说明问题和范围，方便协作，避免重复投入。

先 Fork（派生）项目并创建自己的分支，每个提交请求集中解决一个问题，说明效果和验证方法。纯文档修改检查链接和示例即可；代码变更运行相关测试。已有中英双版的内容同步修改。贡献采用本仓库 Apache-2.0 许可，保留上游版权和许可说明，不要求另签贡献者协议。

不要公开凭据、私密录音/文字稿、内部地址、权重或个人声纹模板；安全问题按[安全说明](SECURITY.md)私密反馈。交流请围绕问题与证据，尊重不同经验的参与者。

## Development checks / 开发检查

Install Python 3.12+, FFmpeg and FFprobe on the test host. Synthetic fixtures are generated and cleaned by the tests. / 测试环境需要 Python3.12+、FFmpeg 与 FFprobe（媒体探测工具）；测试会生成并清理合成素材。

```sh
python -m pip install -e '.[mcp,test]'
python -m unittest discover -s tests -v
python -m unittest discover -s providers/speech/tests -v
python scripts/export_contracts.py
git diff --exit-code -- contracts
python scripts/check_public_tree.py
python scripts/check_configuration.py
```

Run from the repository root. Keep HTTP, CLI and MCP options consistent. Result changes require matching schemas, examples and documentation. Never invent missing timestamps or turn anonymous speaker labels into personal identities. Model accuracy and image/dependency checks are separate from unit tests; see [validation](docs/validation.md) and [benchmark reproduction](docs/release-acceptance.md). Large evaluation media stays outside the source tree; Chinese emotion remains experimental.

从仓库根目录运行，保持 HTTP（网络接口）、CLI（命令行）和 MCP（模型上下文协议）选项一致。输出变更同步合同、示例和文档，不编造时间戳或将匿名说话人当成真实身份。模型质量、镜像与依赖检查不能用单元测试替代；大型评测素材不进入源码，中文情绪继续实验。
