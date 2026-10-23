# Measured quality and recommendations

[中文](quality.zh-CN.md) · [Download reference data](../evaluation/reference-results.json) · [Scoring](accuracy-evaluation.md)

Sonovect brings cloud-class speech recognition to your hardware. On the same public speech samples, local Qwen1.7B matched the two tested cloud services and made fewer character errors in the Mandarin meeting. The results below are dated references for choosing configurations; speech, environmental events and experimental emotions are scored separately.

## Speech: local and cloud on identical audio

Measured on **2026-10-21**. Local: Linux amd64, RTX3090 / 24GiB, Qwen3-ASR-1.7B, paired 0.6B aligner, FireRed VAD and CAM++ speakers. Cloud: Bailian `fun-asr` and `qwen3-asr-flash-filetrans` aliases. The [public corpus manifest](../evaluation/public-corpus.json) fixes recordings, human references and normalized audio hashes.

| Same material | Local selected route | Bailian Fun-ASR | Bailian Qwen3-ASR |
| --- | --- | --- | --- |
| One 39-minute Mandarin meeting |599/8073 character edits (7.42%)|678/8073 (8.40%)|628/8073 (7.78%)|
| Twelve English clips |0/241 word edits|1/241|0/241|

All systems received identical normalized mono 16kHz audio, explicit language hints and no reference-derived hotwords. CER (character error rate) and WER (word error rate) count substitutions, deletions and insertions under the same normalization rules; failed predictions retain their reference denominator. Cloud aliases can change. These speech samples do not establish equivalence for every language, noise condition or service latency.

On ten non-speech event clips, local / Fun-ASR / cloud Qwen inserted 3 / 0 / 2 characters; digital silence produced no speech in all three. The cloud services returned failed/no-word states for 11 and 10 controls respectively; empty predictions are not relabeled successful tasks. Local processing completed all 24 cases.

## Other configuration references

AST held-out target hits are62/80. In a separately declared nine-class DESED scope, precision is92.08%, recall70.63%, and pooled class-negative false alarms24/2665 (0.90%). These denominators describe different tasks and cannot be merged into one accuracy percentage. Default threshold0.1/top5 is the balanced starting point;0.05 favors recall and may add false positives,0.2 is more conservative. Scores are not calibrated probabilities. Generic or unseen sounds and quiet noise can be wrong; zero-signal bypass is not a comprehensive natural-negative test.

MOSS4B/8B strict English emotion matches were20/96 and24/96. Both remain optional experiments; the measured evidence does not justify upgrading solely for emotions. CPU emotion2vec provides closed-set predictions, with unknown/other abstentions, but closed-set outputs do not establish natural Chinese accuracy. Chinese emotion stays experimental. Do not infer mental state from these observations.

Qwen1.7B is the recommended GPU model. The 0.6B alternative had 670/8073 Mandarin edits and 2/241 English edits on the corresponding baseline, so it is an experimental resource tradeoff. The FunASR CPU route had 1005/8073 Mandarin edits (12.45%) on the corresponding baseline; this is a configuration reference, not a new paired cloud run. Paraformer v2.0.9 is an alternate configuration with the same main checkpoint digest, not newly trained weights. CPU speech, optional models and different hardware require their own representative acceptance.

Pitch/energy are deterministic signal measurements with method/window limits, not emotion labels. They can be used without vocal weights. [Configuration](configuration.md) separates all selections; [validation](validation.md) records which current-source and packaged behaviors were actually checked. Broader languages, noise, concurrent capacity and cold-start latency remain deployment-specific.

## Mandarin emotion supplement

Measured on **2026-10-23**. The fixed [CSEMOTIONS source](https://huggingface.co/datasets/ATH-MaaS/CSEMOTIONS/tree/19498e62e6745cf9ec9b69a44b826caa467eac31) supplies existing acted labels. Before inference, select 690 recordings from 10 speakers, with two development speakers and eight held-out speakers; exclude normalized development transcripts from test. Score only the six shared classes: 120 development and 480 test examples. Keep 90 Playfulness examples out of that accuracy denominator. Models receive neither reference text nor labels. The [protocol](quality-protocol.md) specifies the full selection and decision rules.

| Fixed candidate / processing | Development macro F1 | Test strict matches | Test macro F1 |
| --- | ---: | ---: | ---: |
| emotion2vec+base, whole utterance | 0.327 | 226/480 (47.08%) | 0.411 |
| emotion2vec+large, whole utterance | 0.336 | 261/480 (54.38%) | 0.504 |
| SenseVoiceSmall, official Mandarin SER mode | 0.095 | 199/480 (41.46%) | 0.382 |
| Existing base provider, FSMN gate / 10-second windows | 0.307 | 215/480 (44.79%) | 0.426 |
| Existing base provider, FireRed gate / 10-second windows | 0.307 | 216/480 (45.00%) | 0.427 |

Every candidate completed without execution failures. Large has a better held-out score, but its development macro F1 gain is only 0.009, below the predeclared 0.05 replacement requirement. Retain base; do not choose another model using test answers. None qualifies as stable. In whole-utterance classification all three candidates miss every FEARFUL example. For the FSMN windowed provider, 47 test clips have multiple emotion labels; clips longer than 10 seconds reach only 31.93% strict accuracy versus 49.03% for shorter clips. Those groups contain different recordings, so this is an observed association, not proof that windowing alone caused the gap.

Use the first 100 frozen RealDESED test recordings as natural non-speech controls. FSMN admits 32 and produces emotions for 30; FireRed admits 15 and produces emotions for 14. The 14/100 output rate has a descriptive Wilson 95% interval of 8.53–22.14%; FSMN's 30/100 interval is 21.89–39.58%. Dataset collection forbids speech, without proving the absence of every human vocalization. These figures describe the specific gate/provider paths and corpus, not the whole service's universal false-positive rate. Raw classifiers can assign an emotion to non-speech; a speech gate reduces exposure but does not make such labels reliable.

Keep `--voice none` for dependable transcription and request pitch/energy separately with `--measurements` at deployment and `--measure-voice` per job. Use `--voice emotion2vec` and `--analyze-voice` only for experiments, inspect multiple labels and stage/model provenance, and avoid using predicted emotions for automatic decisions. MOSS remains an independent optional description model; its English scores do not establish Chinese emotion accuracy. SenseVoiceSmall is an evaluation comparator, not a selectable deployment backend. These are studio performances and intended labels, not natural-dialogue listener consensus or training-set exclusion proof.

## Real domestic event supplement

Measured on **2026-10-23**. A separate [RealDESED study](https://zenodo.org/records/20056072) fixes 300 development and 300 held-out recordings before inference. Only 12 of its 15 reference classes have declared AST mappings. Coffee machine, light switch and window open/close remain vocabulary gaps; other AST labels are unscored. See the [protocol](quality-protocol.md) for mapping, temporal overlap and source discrepancies.

No development setting meets the predefined precision/quality conditions. Default threshold 0.1, top 5 and 10-second windows therefore remain. At that default, development precision is 71.73%, recall 49.73%, F1 0.587. Lowering the threshold to 0.05 with 5-second windows raises development recall to 64.80%, but precision falls to 63.20%; this is a tradeoff, not an accepted new default.

On the held-out 300 recordings, the retained default has **precision 76.13%, recall 49.43%, F1 0.599** (389 true positives, 122 false positives, 398 false negatives). Pooled class-negative alarms are **122/2813 (4.34%)**, with a descriptive Wilson 95% interval of 3.64–5.15%. There are only two all-negative clips in this 12-class scope: 0/2 false alarms has an upper interval bound of 65.76%, and cannot support a zero-false-alarm claim. Class cells and household recordings are correlated, limiting pooled uncertainty interpretation. This real domestic corpus differs from the earlier DESED/ESC material; do not substitute those older higher numbers for it.

| Reference class | Test positives | Precision | Recall |
| --- | ---: | ---: | ---: |
| bell_ringing | 25 | 61.54% | 32.00% |
| cutlery_dishes | 67 | 81.82% | 67.16% |
| door_open_close | 115 | 70.09% | 65.22% |
| footsteps | 159 | 91.67% | 6.92% |
| keyboard_typing | 56 | 89.80% | 78.57% |
| keychain | 62 | 95.65% | 35.48% |
| microwave | 29 | 100.00% | 51.72% |
| phone_ringing | 62 | 60.00% | 14.52% |
| running_water | 96 | 90.00% | 84.38% |
| toilet_flushing | 41 | 80.43% | 90.24% |
| vacuum_cleaner | 25 | 100.00% | 76.00% |
| wardrobe_drawer_open_close | 50 | 34.33% | 46.00% |

Miss diagnostics at the default: 398 reference presences never reach the threshold, 0 are displaced by the top-k selection. Increasing top-k alone cannot fix low model scores or missing vocabulary. Shorter windows increase computation; tags still describe whole analysis windows. All 300 development and 300 test cases completed without inference failures. Default selection uses the development set; test results are held out from tuning.

## Warm latency reference

Measured on **2026-10-23** using an 8-second Mandarin clip, two warmups and nine interleaved timed runs per route/layout on the same Linux host (RTX3090 for Qwen):

| Warm median | Distributed | Compact |
| --- | ---: | ---: |
| CPU | 1.150s | 1.279s |
| Qwen | 2.077s | 2.269s |

These are shared-host warm timings, not cold-start, concurrency or cloud-latency measurements. See [configuration](configuration.md) for resource controls and [reproduction](release-acceptance.md) for using your own material. The downloadable JSON retains aggregate counts, dates and configurations without task IDs, credentials or media.
