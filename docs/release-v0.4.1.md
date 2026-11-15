# Sonovect 0.4.1

0.4.1 is a dependency-maintenance release. Its speech features and connection formats are the same as [0.4.0](release-v0.4.0.md).

- Apply five official OpenSSL 3.5 security fixes, with upstream regression tests and actual installed-library verification. See the [dependency review](security/release-041-advisories-20261115.md).
- Refresh compatible certificate, multipart-upload, validation and CLI dependency patches in the maintained runtime locks.
- Remove the obsolete 0.3 application-overlay Dockerfile and duplicate transport lock; use the full maintained Dockerfiles.
- Keep the twelve documented, reviewed system-library limitations visible. This is not a zero-vulnerability claim.

Download the matching client/source from [v0.4.1](https://github.com/talentshf/sonovect/releases/tag/v0.4.1). Build all service roles from the same source revision. Deployment operators should drain active jobs and verify a consistent recovery snapshot before replacing containers.

## 中文

这是依赖维护版本，识别、翻译、声音分析和接入方式沿用[0.4.0功能范围](release-v0.4.0.md)。本版补入 OpenSSL（加密库）的五项官方安全修复，并核对测试结果与实际安装库；同时退役旧构建配方，保留其版本历史。十二项尚未由上游修复的系统库限制继续明确记录，不宣称所有漏洞均已消除。
