# ASR deployment advisory review, 2026-11-02

The refreshed Debian image scan added thirteen advisory IDs: ten SQLite issues
(CVE-2026-119371 through CVE-2026-119379, plus CVE-2026-119591), and three GCC
issues (CVE-2026-114690, CVE-2026-114691, CVE-2026-115455). Keep the raw scanner
matches. This review does **not** upgrade or declare the affected libraries fixed.

## SQLite: exact service caller boundary

[SQLite 3.54.0](https://sqlite.org/releaselog/3_54_0.html) contains upstream fixes.
The retained 3.53.4 library is still affected. The new reports require attacker
control over SQL, SQLite/WAL files, changesets, virtual-table structures or
SQL-authorizer decisions; for example, the
[FTS5 overflow](https://security-tracker.debian.org/tracker/CVE-2026-119373)
requires a crafted virtual table and a MATCH query. The source-linked Debian
pages for all ten reports are retained in the explicit advisory baseline.

The inspected Sonovect API accepts media tasks. Its SQLite path is a fixed,
server-owned queue, not the uploaded media path. SQL parameters bind caller
values; the caller cannot submit SQL, a database, a WAL or a changeset to SQLite.
This review binds the exact hashes of API, configuration, file-transcription,
media, remote-input, queue and worker modules. The actual shipped connection is
probed against an in-memory database: defensive mode and cell-size checking are
on; trusted schema, extension loading and ATTACH are disabled. The exact SQLite
library hash, non-root UID, empty capabilities and no-new-privileges profile are
also required. A missing profile, changed caller, changed library or disabled
connection defense fails the classifier. No hostile database is opened by the
probe, and no live queue is used.

This decision covers those exact application-store images only. Standalone
model images with no application-store profile need their own reachability
review; absence of the profile does not silently qualify them. Any SQL endpoint,
database import, uploaded SQLite cache, new database consumer or caller/library
change requires renewed review. An upstream library upgrade remains separate
maintenance work.

## GCC: OS templates and installed exports

The reports concern optional parallel search, boolean-vector construction and
wide-character bitset templates. See the
[assigner's parallel-search description](https://access.redhat.com/security/cve/CVE-2026-114690)
and source references in the exact policy records. The observed OS image has no
compiler headers or affected algorithm/container exports in its hash-bound
libstdc++ library. Parallel settings functions alone are not search algorithms.
The classifier requires all affected export sets to be empty and the library
hash to match; missing evidence fails.

This classifies the distribution packages. It does not classify template code
already compiled into third-party wheels as fixed. Wheel inventories, pinned
sources, their own advisory checks and bounded media/model inputs remain
separate evidence. Adding compilation, user-supplied model code or new native
consumers invalidates this service review.

## Evidence and drift

`tests/test_os_audit.py` rejects changed caller hashes, missing observed fields,
enabled SQL features and affected C++ exports. Actual-image facts and complete
scanner outputs are collected for the selected deployment images. The nineteen
retained service-boundary advisory pages are checked explicitly by
`scripts/check_retained_advisories.py`; the previous nine semantic digests were
verified unchanged before the ten SQLite baselines were added. This check is
not a scheduled monitor, a substitute for image scans or a zero-risk claim.
