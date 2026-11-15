# Retained-advisory review — 2026-11-15

The main-branch check detected changes in two of ten retained Debian advisory pages. The other eight page digests remain unchanged. The full-page drift check stays enabled; this review updates only the two reviewed baselines, without changing severity, source identity, library fingerprints or service controls.

| Record | Current assessment | Decision |
| --- | --- | --- |
| [CVE-2021-45346](https://security-tracker.debian.org/tracker/CVE-2021-45346) | Description, unfixed status and negligible-impact note match the retained snapshot. The distribution table merges forky and sid at3.54.1-2 instead of listing forky at3.53.4-2. The selected source remains3.54.1-2~sonovect13.2. | Retain the existing restricted database/SQL boundary; the issue is not declared library-fixed. |
| [CVE-2026-115456](https://security-tracker.debian.org/tracker/CVE-2026-115456) | Current tracker still lists gcc-14 version14.2.0-19 as vulnerable and unfixed, with a minor-issue note. The description remains an out-of-bounds read/availability/parsing risk in `std::from_chars`. The historical page body was not available locally, so no claim is made that every changed byte concerns unrelated distributions. | Reassess the current page against the retained policy and exact library fingerprint; retain the same low-severity residual limitation and restrictions. |

No runtime library is changed or rescanned by this documentation review. The selected four-role0.4 deployment reuses the reviewed runtime closure; separate wheel-bundled libraries and optional runtime images retain their own qualification scope. Non-root execution, absent compiler tooling and bounded authenticated inputs do not prove every native decoder path unreachable. The original [OS assessment](os-assessment.md), policy reasons and raw advisories remain applicable.

本轮按当前官方公告复核两项摘要变化，未关闭或放宽漂移检查，也未把现有风险说成已修复。SQLite可与旧页面逐项比较；GCC旧整页未在本机取得，当前按固定版本、库摘要和现有服务边界重新判断，保留未修复的低级别可用性与解析限制。该复核不等于新镜像扫描或全可选运行时验收。
