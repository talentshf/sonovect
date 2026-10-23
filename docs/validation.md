# Validation

This file describes Sonovect v0.1.0 only. The supported release scope is in [release scope](release-readiness.md). Tests verify public contracts, independent optional stages, strict inputs, durable jobs, cancellation/retry, media clocks, MCP/CLI, selected assets, security predicates and release packaging.

Run core and provider suites in separate Python processes because their module names may overlap:

```sh
python -m unittest discover -s tests
python -m unittest discover -s providers/speech/tests
python scripts/export_contracts.py
python scripts/check_configuration.py
python scripts/check_public_tree.py
python scripts/check_retained_advisories.py --output /tmp/sonovect-advisory-review.json
```

Install the declared test dependencies in the chosen test environment. Missing libraries or skipped tests are not complete acceptance. Numerical/provider behavior should be checked in the supported Linux runtime. Generated contracts must match the source and examples. Skill validation also checks its standalone resource closure and real interface behavior.

Model quality, actual installed-image scans, real inference and clean installation are separate checks; unit success does not establish any of them. Dated benchmark results are provided separately from developer checks. Raw media and deployment credentials stay outside this product tree.

The retained-advisory check requires the official upstream pages, or saved pages supplied by `--pages`; it fails on incomplete retrieval or changed reviewed records rather than auto-updating the baseline. The 600-event/690-Mandarin supplement has a separate [frozen protocol](quality-protocol.md); it does not replace the earlier speech/CLI/MCP acceptance or qualify natural Chinese emotion.

Compact validation additionally covers all selected-module combinations, model-cache namespaces, helper startup admission, child failure shutdown, graceful queue drain and numeric-only dependency closure. Resolve both compact and distributed recipes across speech/events/vocal/measurement choices and compare selected assets before running real inference. Verify 2 base containers, at most1CPU analysis unit and independent optional MOSS; container consolidation must never imply an unrequested model load.
