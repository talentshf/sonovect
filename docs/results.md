# Output contracts

Speech follows the supported FunASR `AutoModel.generate` field subset. JSON is a source list with `key`, `text`, and available `timestamp`/`sentence_info`. Qwen adapts actual text, alignment and speaker segments to those fields. Missing alignment or speaker evidence is omitted, never synthesized. Speaker IDs are anonymous and recording-local. Every timestamp is an integer millisecond from media-container start, including audio-track delay. Text/SRT are views of the same recognition, not another model call.

SRT requires one successful source and sentence timestamps. Multiple source clocks are not silently merged. Sound tags, model descriptions and measurements never decorate the transcript.

There is one separate `audio-analysis-v1` contract. Each source has `key`, `status`, `stages`, `events`, `emotions`, `voice`, `measurements`, `quality`, successful `engines`, and optional `error`. Stages are `events`, `vocal`, `measurements`, each with `completed|failed|not_requested`; overall status is `completed|partial|failed|not_requested`. Unrequested provider payloads cannot leak into results. A malformed optional stage fails only that stage while retaining valid speech and successful siblings.

Observations include labels, available windows, temporal resolution and optional uncalibrated confidence. AST tags are not calibrated probabilities or guaranteed exact event boundaries. Vocal outputs remain experimental; uncertain presence and abstentions are explicit. Empty observations do not independently establish absence.

Numeric entries carry `kind`, `value` when available, `unit`, `method`, `status`, window and temporal resolution. Pitch is median voiced pYIN F0 over50–600Hz,16kHz audio, frame2048/hop256; energy is whole-window PCM RMS in dBFS. Nonfinite values and invalid windows fail. No usable speech yields no invented numbers; short windows may have energy but unavailable pitch. Numbers are signal properties, not identity, health, emotional truth or calibrated sound pressure.

Generated [speech](../contracts/funasr-result.schema.json) and [analysis](../contracts/audio-analysis.schema.json) schemas define exact fields. [Examples](../examples/analysis.json) illustrate the shape, not measured quality. Export writes both artifacts and a hash manifest into a new directory and validates bytes.
