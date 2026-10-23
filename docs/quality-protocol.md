# Acoustic quality protocol

This document records the method used for the 2026-10-23 RealDESED and CSEMOTIONS reference measurements. [Quality](quality.md) presents the results and recommendations; [reference JSON](../evaluation/reference-results.json) provides aggregate counts. These studies are separate from the 24-case speech corpus, CREMA-D, ESC-10 and DESED.

## References and separation

| Study | Fixed public source | Selection |
| --- | --- | --- |
| Domestic events | [RealDESED 20056072](https://zenodo.org/records/20056072), official validation/test ZIP files | 300 files from each official split, selected before predictions |
| Mandarin emotions | [CSEMOTIONS](https://huggingface.co/datasets/ATH-MaaS/CSEMOTIONS/tree/19498e62e6745cf9ec9b69a44b826caa467eac31) | 690 recordings from 10 professional speakers; 130 development and 560 test including Playfulness; scored six-class subset: 120 development / 480 test |

The ranking seed is `sonovect-quality-expansion-20261023:`. RealDESED filenames are sorted by SHA-256 of seed+filename and the first 300 from each split are selected. Its [paper](https://arxiv.org/abs/2607.16736) specifies collector-disjoint splits and reviewed annotations for all 15 target classes. The public CSV omits collector IDs, preventing an independent reconstruction of the household grouping. The downloaded validation archive contains 1000 metadata entries, whereas the paper reports 999; the actual archive count is retained. Audio packages are checked against the publisher's MD5 and locally frozen SHA-256.

CSEMOTIONS rows are ranked by SHA-256 of seed+decimal row index within each speaker/emotion group. `female001` and `male001` are development speakers; the remaining eight are test speakers. Select at most 10 per group, excluding normalized development transcripts from test candidates; normalization keeps Unicode word characters after case folding. The six shared classes have 20 development and 80 test examples each. 90 Playfulness recordings are reported separately and never mapped to HAPPY or included in six-class accuracy. The official card and repository differ in some speaker/format descriptions; actual source fields and decoded audio govern the study.

The selected official viewer WAV asset paths include the fixed dataset revision; every downloaded recording receives a content digest. Source audio is downmixed by channel mean, resampled with a polyphase filter to 16 kHz and rounded/clipped to signed PCM16. The 600 event clips total 239.51 minutes; 690 Mandarin clips total 104.05 minutes. References, meaningful filenames, transcripts, emotion labels and speaker IDs are absent from the inference input list. Models receive only the same normalized waveform and the declared language/mode. Scoring is offline and separate.

## Event scoring and parameter selection

AST stays at `MIT/ast-finetuned-audioset-10-10-0.4593`, revision `f826b80d28226b62986cc218e5cec390b1096902`. The retained mapping is:

| RealDESED reference | Accepted AudioSet labels |
| --- | --- |
| bell_ringing | Bell; Ringing (of bell); Doorbell; Ding-dong |
| phone_ringing | Telephone bell ringing; Ringtone |
| cutlery_dishes | Dishes, pots, and pans; Cutlery, silverware; Chink, clink |
| door_open_close | Door; Sliding door; Slam |
| footsteps | Walk, footsteps; Shuffle |
| keychain | Keys jangling |
| keyboard_typing | Typing; Computer keyboard; Typewriter |
| microwave | Microwave oven |
| running_water | Water; Water tap, faucet; Sink (filling or washing); Bathtub (filling or washing) |
| toilet_flushing | Toilet flush |
| vacuum_cleaner | Vacuum cleaner |
| wardrobe_drawer_open_close | Cupboard open or close; Drawer open or close |

Coffee machine, light switch and window open/close lack unique AST labels and remain explicit vocabulary gaps. Generic clicking is not substituted for them. The predeclared alias `Ringing (of bell)` does not exist in this pinned model; retain that declaration for traceability, disclose it as unavailable and score only the other predeclared bell aliases. No replacement label is invented. Mapping taxonomy is imperfect: a broad reference, such as phone notifications, is not equivalent to a narrow ringing tag. All other AudioSet predictions are listed as unscored, never automatically called correct or false. This is a 12-class benchmark, not accuracy for the entire 527-class ontology.

Acoustic inference uses CPU-only execution limited to two CPUs and two threads per process. Timing from these classification studies is not a service-latency benchmark.

Report clip-level micro/macro precision, recall and F1; per-class positives/negatives; pooled class-negative false alarms; and all-negative clip false alarms. Only 2 selected clips per split have no event in the12-class scope, so that last denominator is especially weak. Window-level results supplement it: a reference event belongs to a window only when its annotated interval overlaps that window. Window tags do not establish exact event boundaries. Wilson intervals are descriptive; pooled class cells and repeated household recordings are correlated and do not establish a population-wide confidence guarantee.

On development only, compare threshold 0.05/0.1/0.2, top 5/10 and 5/10-second windows. Apply the provider's speech/silence exclusions and top-k before mapping labels, so unscored predictions can still displace target tags. A candidate must improve micro F1 by at least 0.02, retain precision >= 0.85, have no failed inference and not increase all-negative clip false alarms. Freeze one candidate, then compare it with the default once on test. No second test-driven candidate is selected; an unsuccessful candidate leaves defaults unchanged. Failed clips remain in the reference denominator.

## Emotion scoring and decision

Compare existing fixed emotion2vec+base/large snapshots and SenseVoiceSmall in its explicit SER mode, using Mandarin language and `ban_emo_unk=true`. Record actual checkpoint/state verification and all failures, unknown labels, abstentions and multiple labels. The classifier comparison uses entire utterances; the existing base provider is additionally evaluated with its 10-second windows and a reused FSMN speech gate. The same frozen inputs additionally qualify the existing default FireRed gate separately, without parameter tuning; its results never overwrite FSMN evidence.

Report strict six-class accuracy, macro F1, per-class confusion and speaker-stratified results. Select a replacement only if development macro F1 improves by >= 0.05 and test accuracy/F1 do not regress; assess its resource cost separately. Stability additionally requires accuracy and macro F1 >= 0.80, recall >= 0.65 in every shared class, and independent natural Mandarin dialogue references. CSEMOTIONS has acted studio labels rather than independent listener-majority annotations, so this study alone cannot promote Chinese emotion to stable.

For the existing pipeline, use the first 100 fixed RealDESED test clips as natural non-speech controls. Its collection rules prohibit speech, but this does not prove absence of every human vocalization. Report both speech-gate admissions and actual emotion outputs; do not collapse them into an asserted voice-presence truth.

The fixed base checkpoint dates to 2024, earlier than the 2025 CSEMOTIONS release. This chronology reduces overlap concerns but is not a per-file training exclusion proof. All models remain subject to corpus scope and domain shift; larger models are not presumed better.
