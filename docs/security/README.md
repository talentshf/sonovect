# Security evidence

- [OS advisory assessment](os-assessment.md): exact source versions,63 per-ID decisions and eight retained service-boundary limitations.
- [Machine-readable OS policy](../../providers/speech/shared/os-security/advisory-policy.json): scoped proof predicates, with raw matches retained.
- [Retained advisory snapshots](retained-advisories.json) and [explicit drift check](../../scripts/check_retained_advisories.py): require renewed review when official records or accepted source versions change; never auto-accept findings.
- [Python audit policy](dependency-dispositions.json): current accepted exception list is empty; unknown/skipped findings fail.
- [Media build](media-build.json): pinned decoder build and scope.
- [Component source declarations](model-sources.json): dated fixed-source evidence; component information is separate from functional qualification.
- [Release readiness](../release-readiness.md): current candidate acceptance and limits.

An absent-code disposition requires actual per-image file evidence. Source repairs, absent code and accepted service-boundary limits are distinct. No single scanner covers all upstream source, bundled native libraries or the host.
