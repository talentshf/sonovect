# Security

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/talentshf/sonovect/security/advisories/new). Reports are private to the reporting and maintainer teams; do not post vulnerability details in ordinary issues or discussions.

Include the exact version, affected component, reproducible steps and expected impact, using synthetic or openly licensed media. Share only the minimum data needed to reproduce the issue. Do not include live credentials or private recordings.

中文：请使用 [GitHub 私密漏洞报告](https://github.com/talentshf/sonovect/security/advisories/new)。报告不会发布到普通问题区或讨论区。请说明版本、组件、复现步骤与影响，使用合成或公开许可素材，不附带真实凭据和私密录音。

The API requires an operator-supplied bearer token. One token grants access to
all jobs in one installation: this is a single trust-domain service. Use separate
installations for separate trust domains. Default recipes bind the API to
localhost; use TLS, authentication and request limits at a reverse proxy when
serving a wider network. Model ports must remain private. The stdio MCP client
accepts uploads only below its explicitly configured input root.

Uploads have aggregate byte/count limits, content-based probing, decoded-duration
and decoder-time bounds. Original filenames and arbitrary server filesystem
paths do not select resources. Speech results follow the documented FunASR
contract; sound/model output is untrusted data, never a command to execute.

Inputs/results expire according to configuration. Expiry does not guarantee
physical erasure from SSDs, SQLite journals, snapshots or operator backups.
Operators own host security, disk protection, retention and recovery disposal.
Containers must run with the documented unprivileged user, dropped capabilities
and no-new-privileges. They are not system-login or host-administration images.

## Current dependency and OS checks

Sonovect v0.1.0 uses reviewed role-specific Linux amd64/Python3.12 locks: Torch2.14.1
(CPU or official cu132), CPU TorchAudio2.11.0, Transformers5.20.2,
FunASR1.4.16 and ModelScope1.40.2. MOSS is an explicitly identified derived
inference package. Demo UI frameworks are not installed by maintained recipes.
Keep raw installed-package Python audit receipts; the
[Python audit check](scripts/check_dependency_audit.py) rejects new findings,
skipped packages and scoped version drift.

The maintained candidate retains the exact-source Debian13 backports of util-linux2.42.4, ACL2.4.0, ncurses6.6, glibc2.43-7, SQLite3.53.4-2 and zlib1.3.1 with a narrow upstream CRC fix. It installs no unstable binary packages and changes no host OS. Hash-locked source, complete packaging changes, modified corresponding source packages, build instructions and inventories remain under `/usr/local/share/sonovect-os-security` in every role image. The runtime removes setuid/setgid bits and unused shell, Perl, archive and account-administration programs. Use direct Python diagnostics; rebuild images to change software.

A source-package advisory can match a library while the affected executable/module is absent. Findings require exact per-image package/file evidence; absence of a distro fix does not close them. The [OS audit gate](scripts/check_os_audit.py) rejects unreviewed findings at **all severities**, severity/source-version drift, incomplete inventories and missing applicability proof. Every raw match is retained: the actual raw package/advisory match count per candidate role, not a zero scanner count. Actual-role Python installed-package audits must have no unreviewed matches or skipped third-party packages; project-authored and derived model-runtime code is reviewed as source.

All 63 lower/unknown IDs are [individually assessed](docs/security/os-assessment.md): 19 source-fixed, 33 affected programs/modules absent, three different versions/components/platform branches, and eight findings with **completed project-side assessment and mitigation within the supported service boundary**. Upstream limitations remain documented for maintenance. Those eight concern disputed/unfixed glibc behavior and corrupt SQLite databases/arbitrary SQL. Maintained media-job APIs do not accept arbitrary regex, ELF execution, SQL or database replacement. All final images additionally remove ldd and the grep family; each queue connection enables SQLite defensive and cell-size checks, disables trusted schema and extension loading, and forbids attached databases. This does not repair those libraries or cover arbitrary operator code. Reassess any new caller/trust boundary and rebuild/scan when advisory data changes.

Before release or dependency maintenance, use `python scripts/check_retained_advisories.py --output NEW_RECEIPT.json` to compare the eight official records with the reviewed baseline. Incomplete evidence, upstream changes and source-version drift require renewed review; the tool never updates that baseline. This explicit maintenance check adds no scheduler and does not replace actual-image scans. See the [review procedure](docs/security/os-assessment.md#rechecking-retained-limits).

The media worker builds FFmpeg9.0.2 from verified source, without network
protocols or compressed-video decoders. Its source, commands and LGPL notice
remain in the image. Model workers receive normalized audio. OS-package scans,
Python-package audits and wheel-bundled native libraries have different coverage;
none alone establishes that a complete image has no vulnerabilities.

See [current release review](docs/release-readiness.md) for actual completed
checks, support scope and residual risk. Distribution availability is described in
[PUBLICATION.md](PUBLICATION.md).

The compact CPU analysis unit and distributed AST role have CPU-only dependency closures and no MOSS/CUDA packages. MOSS is an optional separately prepared voice service. Event/vocal failures are explicit partial results; they never create fabricated successful speech. Role selection is not a substitute for scanning the actual installed image.

## Image evidence checks

The release checker validates supplied image evidence. It does not publish a release, change repository visibility or configure reporting channels. Repository and release operations are verified separately; source releases and deployed images can have different revisions.

`python scripts/check_release.py --evidence AUDIT_DIRECTORY --images IMAGES_JSON --revision SOURCE_COMMIT` verifies all13actual image role identities, installed-package audit results and source/license inventories. It rejects unknown findings, skipped packages, mismatched image/source versions and incomplete evidence. Raw scanner matches are preserved; an engineering pass does not mean zero vulnerabilities. Numeric measurements run independently inside the optional compact CPU analysis unit or a separate distributed CPU service, without model weights; the measurements-only compact image also omits model frameworks; emotion2vec and MOSS remain optional experimental components. Source declarations are retained as informational records; selecting a component does not issue an authorization on its upstream author’s behalf.
