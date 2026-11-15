# OpenSSL dependency maintenance — 0.4.1

The [2026-11-10 OpenSSL advisory](https://openssl-library.org/news/secadv/20261110.txt) provides public fixes before its scheduled December release. This release keeps the Debian 13 / OpenSSL 3.5 ABI and backports the official `openssl-3.5` commits to Debian's 3.5.7 security source. It does not replace the host operating system or claim to be the unreleased OpenSSL 3.5.10.

| Finding | Official 3.5 fix |
| --- | --- |
| CVE-2026-88822, automatic QUIC peer detection | [1a73dc590cba](https://github.com/openssl/openssl/commit/1a73dc590cbad62d6f0329ea4779eadaa8d8fd75) |
| CVE-2026-88823, AES-GCM-SIV AAD handling | [159e1de0c448](https://github.com/openssl/openssl/commit/159e1de0c448d7b9f09ad768c8e141def4aa1eb4) |
| CVE-2026-95691, QUIC retransmission storage lifetime | [f6244675833e](https://github.com/openssl/openssl/commit/f6244675833e097c2429a40d1b206d95385bd42f) |
| CVE-2026-95692, AES-GCM-SIV IV length | [257a3427aa0e](https://github.com/openssl/openssl/commit/257a3427aa0ef8d9dd2ef5b3e2d1c021a221b116) |
| CVE-2026-107496, order-1 EC key generation | [a0051cfe699b](https://github.com/openssl/openssl/commit/a0051cfe699bf5a047bc1c4faef65f80f7987366) |

The [source lock](../../providers/speech/shared/os-security/openssl-source-lock.json) pins source archives, original patch bytes, corresponding upstream tests and the exact custom Debian version. One test-only patch needs insertion-context relocation because Debian 3.5.7 lacks unrelated later tests: its 401 added function lines and five test registrations are unchanged. Both original and adapted patches remain in the recipe. Production fixes apply directly, without fuzzy patch application.

The builder runs Debian's upstream OpenSSL test target without `nocheck`. An additional peer-address probe forces automatic detection on connected IPv4 and IPv6 UDP sockets without sending data. The old maintained library reproduces an incorrect IPv6 result; the new bundle must pass both address families. Actual library digests, successful tests, source lock and modified corresponding source travel with the binaries. Per-role qualification rejects missing receipts, altered library bytes, changed locks or the old unpatched source version. The earlier TLS-only applicability exception is retired.

Twelve reviewed service-boundary limitations remain in glibc, SQLite and GCC. Their existing advisory snapshots and exact-library restrictions remain required; this release does not describe those libraries as fully repaired. Scanner raw matches and Python/native-library coverage stay separate. OpenTelemetry API remains at least 1.45.2 in maintained Sonovect runtimes and clients.

The obsolete 0.3 application-overlay Dockerfile and duplicate transport lock are removed. Maintained full role Dockerfiles are the single build path; historic release tags retain the original recipes.
