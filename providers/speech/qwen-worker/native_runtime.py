"""Thin runtime over maintained Transformers Qwen ASR/aligner implementations."""
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class Transcription:
    text: str
    language: str
    time_stamps: object = None


def alignment_items(predictions, words, milliseconds_per_class=80):
    """Decode model classes without upstream timestamp interpolation or repair."""
    if len(predictions) != 2 * len(words):
        return None
    return SimpleNamespace(items=[SimpleNamespace(
        text=word, start_time=predictions[2 * i] * milliseconds_per_class / 1000,
        end_time=predictions[2 * i + 1] * milliseconds_per_class / 1000,
    ) for i, word in enumerate(words)])


class NativeQwenASR:
    @classmethod
    def from_pretrained(cls, model_path, *, dtype, device_map, max_inference_batch_size,
                        max_new_tokens, forced_aligner, forced_aligner_kwargs, **kwargs):
        from transformers import (AutoProcessor, Qwen3ASRForConditionalGeneration,
                                  Qwen3ASRForTokenClassification)
        safe = {"trust_remote_code": False, "local_files_only": True, "use_safetensors": True}
        instance = cls()
        instance.model = Qwen3ASRForConditionalGeneration.from_pretrained(
            model_path, dtype=dtype, device_map=device_map, **safe, **kwargs).eval()
        instance.processor = AutoProcessor.from_pretrained(
            model_path, trust_remote_code=False, local_files_only=True)
        instance.aligner = Qwen3ASRForTokenClassification.from_pretrained(
            forced_aligner, **safe, **forced_aligner_kwargs).eval()
        instance.aligner_processor = AutoProcessor.from_pretrained(
            forced_aligner, trust_remote_code=False, local_files_only=True)
        instance.max_new_tokens = max_new_tokens
        instance.batch_size = max_inference_batch_size
        return instance

    def transcribe(self, *, audio, context="", language=None, return_time_stamps=True):
        import torch
        if any(rate != 16000 for _, rate in audio):
            raise ValueError("native_qwen_requires_16khz")
        waves = [wave for wave, _ in audio]
        languages = language if isinstance(language, list) else [language] * len(waves)
        prompts = context if isinstance(context, list) else [context] * len(waves)
        with torch.inference_mode():
            inputs = self.processor.apply_transcription_request(
                audio=waves, language=languages, prompt=prompts,
                processor_kwargs={"sampling_rate": 16000, "padding": True, "return_tensors": "pt"}).to(self.model.device, self.model.dtype)
            output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
            parsed = self.processor.decode(
                output[:, inputs["input_ids"].shape[1]:], return_format="parsed")
            results = []
            for wave, hint, value in zip(waves, languages, parsed):
                text = value["transcription"].strip()
                detected = value.get("language") or hint or "unknown"
                spans = self._align(wave, text, detected) if return_time_stamps and text else None
                results.append(Transcription(text, detected, spans))
            return results

    def _align(self, waveform, text, language):
        # ASR supports more languages than the official aligner. Missing word
        # alignment must not discard a successful transcription.
        supported = {"Chinese", "English", "Cantonese", "French", "German", "Italian",
                     "Japanese", "Korean", "Portuguese", "Russian", "Spanish"}
        if language not in supported:
            return None
        inputs, word_lists = self.aligner_processor.prepare_forced_aligner_inputs(
            audio=[waveform], transcript=[text], language=[language],
            processor_kwargs={"sampling_rate": 16000, "padding": True, "return_tensors": "pt"})
        inputs = inputs.to(self.aligner.device, self.aligner.dtype)
        logits = self.aligner(**inputs).logits
        mask = inputs["input_ids"][0] == self.aligner.config.timestamp_token_id
        predictions = logits.argmax(dim=-1)[0][mask].cpu().tolist()
        return alignment_items(predictions, word_lists[0],
                               self.aligner_processor.timestamp_segment_time)
