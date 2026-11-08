"""Pinned VibeVoice 1.5B streaming adapter using the upstream native methods."""
from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass
class LiveText:
    text: str
    speaker_segments: list[dict]


def speaker_segments(text):
    """Read only model-emitted labels. Preserve raw text and omit all timing."""
    markers = list(re.finditer(r"(?:^|\n)[ \t]*Speaker[ \t]+([0-9]+)[ \t]*:", text))
    rows, identities = [], {}
    if not markers:
        return []
    if text[:markers[0].start()].strip():
        rows.append({"text": text[:markers[0].start()]})
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        value = text[marker.end():end]
        if value:
            rows.append({"speaker_id": identities.setdefault(marker.group(1), len(identities)), "text": value})
    return rows


class VibeVoiceStreamingEngine:
    def __init__(self, settings):
        self.settings, self.model, self.processor = settings, None, None
        self.chunk_samples, self.window_samples = 22 * 3200, 26 * 3200

    def load(self):
        if self.model is not None:
            return
        import torch
        from .assets import catalog, verify
        from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
        from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor
        root = Path(self.settings.realtime_model_path)
        verify(root, catalog()["vibevoice-stream-1.5b"])
        cfg = json.loads((root / "preprocessor_config.json").read_text())
        if {k: cfg.get(k) for k in ("target_sample_rate", "speech_tok_compress_ratio", "chunk_frames", "lookahead_frames")} != {
                "target_sample_rate": 24000, "speech_tok_compress_ratio": 3200, "chunk_frames": 22, "lookahead_frames": 4}:
            raise RuntimeError("vibevoice_stream_checkpoint_mismatch")
        device = self.settings.realtime_device
        if device.startswith("cuda"):
            free, total = torch.cuda.mem_get_info(device)
            budget = int(total * self.settings.realtime_gpu_memory_utilization)
            if free < budget + 1024**3:
                raise RuntimeError("vibevoice_stream_gpu_capacity_unavailable")
            torch.cuda.set_per_process_memory_fraction(self.settings.realtime_gpu_memory_utilization, device)
        processor = VibeVoiceASRProcessor.from_pretrained(str(root), local_files_only=True)
        if processor.tokenizer.text_chunk_end_id is None:
            raise RuntimeError("vibevoice_stream_tokenizer_mismatch")
        model = VibeVoiceASRForConditionalGeneration.from_pretrained(
            str(root), dtype=torch.bfloat16 if device.startswith("cuda") else torch.float32,
            attn_implementation="sdpa", local_files_only=True,
        ).to(device).eval()
        self.model, self.processor = model, processor

    def start(self, options):
        import numpy as np
        import soxr
        import torch
        self.load()
        # One resampler per session preserves filter state across client frames.
        context = ", ".join(options.hotwords)
        if options.language:
            context = (context + "; " if context else "") + "Language hint: " + options.language
        with torch.inference_mode():
            stream = self.model.init_streaming_state(self.processor.tokenizer, context_info=context or None)
        return {"stream": stream, "resampler": soxr.ResampleStream(16000, 24000, 1, dtype="float32"),
                "buffer": np.zeros(0, dtype=np.float32), "texts": [], "received_samples": 0,
                "advanced_samples": 0, "finished": False}

    def _step(self, state, window):
        import torch
        with torch.inference_mode():
            audio = torch.from_numpy(window).to(self.settings.realtime_device)
            features = self.model.encode_speech(audio.unsqueeze(0))
            text, _ = self.model.streaming_generate_step(
                audio_features=features, streaming_state=state["stream"],
                tokenizer=self.processor.tokenizer, max_new_tokens=256, temperature=0.0)
        if not isinstance(text, str):
            raise RuntimeError("vibevoice_stream_output_invalid")
        state["texts"].append(text)

    def _drain(self, state, flush=False):
        import numpy as np
        while (len(state["buffer"]) >= self.window_samples if not flush else
               state["advanced_samples"] < state["received_samples"]):
            window = state["buffer"][:self.window_samples]
            if len(window) < self.window_samples:
                window = np.pad(window, (0, self.window_samples - len(window)))
            self._step(state, window)
            state["buffer"] = state["buffer"][self.chunk_samples:]
            state["advanced_samples"] += self.chunk_samples
        text = "".join(state["texts"])
        return LiveText(text, speaker_segments(text))

    def push(self, state, pcm):
        import numpy as np
        if state["finished"]:
            raise RuntimeError("vibevoice_stream_already_finished")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        resampled = state["resampler"].resample_chunk(audio)
        state["buffer"] = np.concatenate([state["buffer"], resampled])
        state["received_samples"] += len(resampled)
        return self._drain(state)

    def finish(self, state):
        import numpy as np
        if state["finished"]:
            raise RuntimeError("vibevoice_stream_already_finished")
        state["finished"] = True
        tail = state["resampler"].resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        state["buffer"] = np.concatenate([state["buffer"], tail])
        state["received_samples"] += len(tail)
        return self._drain(state, flush=True)
