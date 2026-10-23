# Operations

Keep deployment environment/credentials in the native secret mechanism, model caches separate from job data, and model ports private. Jobs use `jobs-v1.sqlite3`, retained inputs and immutable result artifacts under the configured data root. Do not replace a live database with an older snapshot: preserve jobs admitted after the snapshot.

Before a deployment change retain accepted image identities, configuration, selected model identities and a consistent database/input snapshot through the service UID. Validate recovery in an isolated instance. Source and skill updates do not themselves switch a running service. Use a separate installation for different trust domains.

Inspect liveness/readiness, worker leases and task state separately. Health discovery does not load every model. Test a permitted short speech file, read actual speech/analysis, export with hashes, restart and read retained bytes. For optional stages, verify missing/corrupt weights and capacity/failure recovery while valid speech survives. Inputs may expire before results; retry requires retained input.

Defaults are24hour input and168hour result retention. Retention deletion does not promise physical erasure from SSDs, journals or backups. Logs should contain task IDs and bounded error codes, not credentials or private transcripts. A timeout continues under the same job ID; cancellation prevents publication, though active inference may finish internally.

All services run unprivileged with dropped capabilities and no new privileges. Do not execute user uploads, caller SQL/regex or arbitrary plugins in maintained images. Rebuild immutable images to change dependencies; keep corresponding source/materials. [Security](../SECURITY.md) records the eight scoped library limitations and scan coverage.
