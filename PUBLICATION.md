# Releases / 发行

Sonovect is open source under Apache-2.0. Get **v0.1.0** from the [GitHub release](https://github.com/talentshf/sonovect/releases/tag/v0.1.0), or clone the [repository](https://github.com/talentshf/sonovect). The release provides source, a clean Git bundle, the Python client, a source distribution and the standalone agent skill. Verify downloaded files with the attached `SHA256SUMS`.

Sonovect 已按 Apache-2.0 开源。通过 [v0.1.0 发行页](https://github.com/talentshf/sonovect/releases/tag/v0.1.0)下载源码、干净 Git（版本管理）历史包、Python 客户端、源码安装包及独立智能体技能；附件使用 `SHA256SUMS` 校验。也可以直接克隆项目仓库。

Container recipes build locally. Model weights are downloaded separately according to your selections; this release does not distribute prebuilt registry images or publish a package to PyPI. Follow [deployment](deploy/README.md) and [agent setup](docs/agent-setup.md).

容器按项目配方在本地构建，模型权重按选型另行下载；首版未发布公共镜像或 PyPI 软件包。请按[部署手册](deploy/README.md)和[智能体接入](docs/agent-setup.zh-CN.md)安装。

## Security / 安全反馈

Use [GitHub private vulnerability reporting](https://github.com/talentshf/sonovect/security/advisories/new) for sensitive security reports. See [SECURITY.md](SECURITY.md). Ordinary bugs and proposals belong in [Issues](https://github.com/talentshf/sonovect/issues); usage questions and deployment experiences belong in [Discussions](https://github.com/talentshf/sonovect/discussions).

安全问题通过 [GitHub 私密漏洞报告](https://github.com/talentshf/sonovect/security/advisories/new)提交；普通缺陷与建议使用问题区，使用交流与部署经验使用讨论区。欢迎按[贡献指南](CONTRIBUTING.md)参与。

## Scope / 范围

The product tree includes supported contracts, deployment recipes, dated reference results and the agent skill. It contains no private project-management records, previous development history, credentials, media or model weights. Chinese emotion remains experimental; public acted-label measurements do not establish reliable natural-dialogue recognition. Upstream model declarations remain available as component information.

当前产品、接口、部署说明、测试参考和技能随源码维护。私有管理记录、旧开发历史、凭据、媒体和权重不进入发行。中文情绪继续实验，各模型来源和上游声明按实保留。

[Release notes / 发行介绍](docs/release-v0.1.0.md) · [Scope / 发行范围](docs/release-readiness.md) · [Quality / 测试参考](docs/quality.md) · [Component sources / 组件来源](docs/model-licenses.md)
