# v0.2.0 dependency review, 2026-11-07

Fresh image scans and retained-page checks are separate publication gates.
The first candidate failed these gates; it is not an accepted release artifact.

## Fixed library sources

The recipes now rebuild hash-locked official Debian SQLite **3.54.1-2** sources
for Debian 13. This includes the upstream 3.54.0 fixes for CVE-2026-119371 through
CVE-2026-119379 and CVE-2026-119591. These ten IDs move from the previous exact
caller-boundary assessment to fixed-source records. The older corrupt-database
limitation CVE-2021-45346 remains a separately disclosed service boundary.
See the [Debian SQLite advisory](https://security-tracker.debian.org/tracker/CVE-2026-119373).

The zlib recipe uses the official trixie-security source
**1:1.3.dfsg+really1.3.1-1+deb13u1**. Both Debian patch files are hash checked:
the existing negative CRC-length fix remains, and the gzip write-buffer backport
fixes [CVE-2026-76844](https://security-tracker.debian.org/tracker/CVE-2026-76844)
and [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091).
The former narrower version-only disposition for 85091 is superseded by the
explicit patched source, including Debian's backport for the older gzwrite code.
The CRC patch is not applied twice.

Source descriptors, archive lengths and SHA-256 values are pinned in
`additional-source-lock.json`. Runtime package versions and actual image facts
must match those exact rebuilt sources. Building a recipe or reviewing source
alone does not qualify its installed images.

## Removed entry points and build transport

[CVE-2026-109518](https://security-tracker.debian.org/tracker/CVE-2026-109518)
requires an APT package download with redirects and non-zero retry configuration.
Every project build-time APT command explicitly sets `Acquire::Retries=0` before
package operations. Final immutable images remove APT commands, package download
methods and APT shared libraries. Raw distribution package metadata stays in the
inventory. The classifier requires observed absence of all these components;
missing evidence or a restored downloader/library fails the check. Host package
managers and running services are not modified by recipe preparation.

The current distribution update installs APT **3.0.4**, which fixes 109518.
The older [CVE-2011-3374](https://security-tracker.debian.org/tracker/CVE-2011-3374)
still appears against that exact version. Its record requires observed removal
of `apt-key` from the actual image. The new package version does not itself
justify dismissing this older finding, and unreviewed versions still fail.

[CVE-2026-82560](https://security-tracker.debian.org/tracker/CVE-2026-82560)
affects the Perl Pod::Text formatter. The existing runtime minimization already
removes Perl and its base modules. The new disposition requires actual absence
of the formatter, interpreter and `pod2text` command. It is code removal, not a
claimed fix to the distribution's Perl package.

## Retained-page changes

Eleven of the nineteen previously retained Debian pages changed. Ten now list
the SQLite fixes in unstable 3.54.1 and add the trixie maintenance note; their
upstream vulnerability descriptions and fixed commits are unchanged.
CVE-2021-45346 only changes the distribution version table and remains unfixed.
The other eight page digests are unchanged. After the SQLite source upgrade,
the ten fixed IDs remain explicit in the image policy and history; the retained
service-boundary baseline contains the remaining nine IDs. Future page changes
still require explicit review. No baseline update suppresses raw scanner output.

The historical [2026-11-02 review](asr-runtime-advisories-20261102.md) describes
the earlier library and caller snapshot. This document records the v0.2.0 change
without rewriting that history. Existing glibc boundaries, optional experimental
emotion analysis, native-wheel audit limits and model-quality limits remain.
