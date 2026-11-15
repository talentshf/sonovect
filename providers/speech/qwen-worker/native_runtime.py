"""Thin runtime over maintained Transformers Qwen ASR/aligner implementations."""
from dataclasses import dataclass
from types import SimpleNamespace
import logging
import re
import unicodedata


logger = logging.getLogger(__name__)


def _context_units(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def context_echo_suspected(text, context):
    """Identify copied hints for acoustic rechecking, never for text deletion.

    Individual vocabulary matches are expected. Adjacent distinct terms or a
    longer copied context span warrant another decode with an empty system
    prompt. That decode can still confirm a genuinely spoken list/repetition.
    """
    if not context:
        return False
    candidate = _context_units(text)
    if not candidate:
        return False
    lines = context.splitlines()
    for line in lines:
        vocabulary = re.match(r"\s*(?:Vocabulary|Technical terms|术语|热词)\s*[:：]\s*(.*)", line, re.I)
        if not vocabulary:
            continue
        terms = list(dict.fromkeys(filter(None, (_context_units(term) for term in
                     re.split(r"[,，、;；]", vocabulary.group(1))))))
        for left, right in zip(terms, terms[1:]):
            joined = left + right
            if len(joined) >= 6 and joined in candidate:
                return True
    # Also cover legacy unlabelled requests, configured prose and rolling
    # context. A fixed-size span bounds matching work even for long hints.
    hint = _context_units("\n".join(re.sub(
        r"^\s*(?:Vocabulary|Technical terms|术语|热词)\s*[:：]", "", line, flags=re.I)
        for line in lines))
    width = 12
    if min(len(candidate), len(hint)) < width:
        return False
    spans = {hint[i:i + width] for i in range(len(hint) - width + 1)}
    return any(candidate[i:i + width] in spans for i in range(len(candidate) - width + 1))


@dataclass
class Transcription:
    text: str
    language: str
    time_stamps: object = None
    context_echo_rechecked: bool = False


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
        instance.aligner = None
        instance.aligner_processor = None
        if forced_aligner:
            instance.load_aligner(forced_aligner, forced_aligner_kwargs)
        instance.max_new_tokens = max_new_tokens
        instance.batch_size = max_inference_batch_size
        return instance

    def load_aligner(self, path, kwargs):
        if self.aligner is not None:
            return
        from transformers import AutoProcessor, Qwen3ASRForTokenClassification
        processor = AutoProcessor.from_pretrained(path, trust_remote_code=False, local_files_only=True)
        aligner = Qwen3ASRForTokenClassification.from_pretrained(
            path, trust_remote_code=False, local_files_only=True, use_safetensors=True, **kwargs).eval()
        self.aligner_processor, self.aligner = processor, aligner

    def transcribe(self, *, audio, context="", language=None, return_time_stamps=True):
        import torch
        if any(rate != 16000 for _, rate in audio):
            raise ValueError("native_qwen_requires_16khz")
        waves = [wave for wave, _ in audio]
        languages = language if isinstance(language, list) else [language] * len(waves)
        prompts = context if isinstance(context, list) else [context] * len(waves)
        if not (len(waves) == len(languages) == len(prompts)):
            raise ValueError("audio_language_context_count_mismatch")
        with torch.inference_mode():
            parsed = self._decode(waves, languages, prompts)
            results = []
            for wave, hint, prompt, value in zip(waves, languages, prompts, parsed):
                text = value["transcription"].strip()
                rechecked = context_echo_suspected(text, prompt)
                if rechecked:
                    # Re-listen to only this chunk, within the same task/model
                    # call, without any request, configured or rolling hints.
                    # Do not remove matching words or reuse their alignments.
                    value = self._decode([wave], [hint], [""])[0]
                    text = value["transcription"].strip()
                    logger.info("context_echo_rechecked_without_context")
                detected = value.get("language") or hint or "unknown"
                spans = self._align(wave, text, detected) if return_time_stamps and text else None
                results.append(Transcription(text, detected, spans, rechecked))
            return results

    def _decode(self, waves, languages, prompts):
        inputs = self.processor.apply_transcription_request(
            audio=waves, language=languages, prompt=prompts,
            processor_kwargs={"sampling_rate": 16000, "padding": True, "return_tensors": "pt"}).to(self.model.device, self.model.dtype)
        output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        parsed = self.processor.decode(
            output[:, inputs["input_ids"].shape[1]:], return_format="parsed")
        if len(parsed) != len(waves):
            raise RuntimeError("asr_result_count_mismatch")
        return parsed

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
