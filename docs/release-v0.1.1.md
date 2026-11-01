# Sonovect v0.1.1

This maintenance release adds bounded, read-only readiness diagnostics across HTTP, CLI, MCP and container health checks. `/ready` keeps its 200/503 semantics and existing fields while adding safe failure codes and logical components. The authenticated detail endpoint reports all observed required failures and optional warnings. Older servers remain readable through the new client. Diagnostics never load models, submit jobs or automatically repair infrastructure.

Provider discovery runs concurrently with aggregate deadlines and response limits. GPU probes distinguish missing devices, denied access, missing tools, library mismatches and timeouts; oversized/timed-out probe subprocesses are reaped. Idle model unloading and normal busy workers do not fail readiness. The report cache is bounded to 2 seconds; concurrent callers share one collection.

The affected model-role locks move hydra-core to 1.3.8 for [GHSA-wf6j-7hvr-gr93](https://github.com/advisories/GHSA-wf6j-7hvr-gr93). The newly published [gettext locale advisory](https://security-tracker.debian.org/tracker/CVE-2026-84243) is a ninth retained library limitation, with an explicitly checked C locale service boundary; it is not a claimed glibc repair. [Security assessment](security/os-assessment.md) records the distinction and required image evidence.

Install matching client/service versions, then use `sonovect ready --details` or MCP `sonovect_ready(details=true)`. Full behavior, codes and compatibility are in the [readiness guide](readiness.md). Existing transcript/analysis formats, model identities and job recovery behavior are unchanged. Previously published quality measurements remain dated reference results, not new quality evaluations for this maintenance release.

The v0.1.0 tag and release artifacts remain fixed. Public artifacts contain no weights, credentials, private deployment data or project-management history.
