# Accuracy evaluation

Install `pip install '.[evaluation]'`, then score saved outputs offline:

```sh
sonovect-evaluate dataset.json predictions.json report.json
```

The tool never calls a model or uploads reference text. The dataset and prediction
files each contain a `cases` list with identical unique IDs. Dataset cases have
`id`, `group`, `language`, `text`, and optionally `duration_ms`/`segments` with
`start_ms`, `end_ms`, `speaker` and text. Predictions contain `id`, terminal
`status`, `transcript` (one FunASR speech result), and optional `analysis`.
The report binds both input files by SHA-256 and refuses to overwrite a report.
Keep model outputs and independent human/corpus references in different files.

For repeatable inference through an isolated public API, use
`python scripts/run_benchmark.py --help`. It verifies the frozen dataset and all
audio hashes before submission, retains job IDs for resumption, and verifies
exported artifact digests. It sends audio and declared options only; scoring
remains a separate offline step. See the
[public acceptance summary](release-acceptance.md) for the frozen corpus
selection, resource conditions and interpretation limits; see
[configuration recommendations](configuration.md) for deployment and tuning.

CER is edit distance divided by reference character count; English WER uses
word tokens. Text is normalized with NFKC and case folding, corpus angle tags
are removed, and punctuation/whitespace are excluded from CER. Fillers, names,
numbers and lexical differences remain errors. Failed cases stay in the
reference denominator as empty predictions. Rates are not capped at 100%.
Meeting text uses segment onset order; this is not permutation-invariant cpCER,
so overlapping speech and ordering differences can contribute to text errors.

DER divides missed speaker time, false-alarm speaker time and speaker confusion
by reference speaker time. Speaker IDs are matched using an exact global
one-to-one assignment maximizing temporal overlap. Both overlapping speech and
unmatched clusters count. Results include zero-collar and 250 ms-collar scores;
the latter excludes a 250 ms region on each side of every reference boundary.
This exact implementation supports up to 16 distinct reference speakers.

For sound datasets with a labeled primary event, put a predeclared
`acceptable_event_labels` list on each case. Bilingual aliases are matched with
English word boundaries or literal non-English phrases. Report target-event
recall and all predicted labels. A single primary label is not exhaustive
annotation of secondary sounds, so it cannot establish event precision.
For known digital silence set `expect_silence: true` to inspect speech/event
false alarms explicitly. Do not revise aliases after inspecting predictions.

Commit the scoring code, normalization policy, source revisions and aggregate
results. Keep audio and per-case detailed artifacts outside Git under their
original licenses and access controls. Report dataset scope and sample count;
a small exploratory round is not a population-wide quality guarantee.
