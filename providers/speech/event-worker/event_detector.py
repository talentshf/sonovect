"""Optional closed-vocabulary AudioSet tagging, independent of vocal descriptions."""
import logging
import os
import threading

MODEL_ID = 'MIT/ast-finetuned-audioset-10-10-0.4593'
REVISION = 'f826b80d28226b62986cc218e5cec390b1096902'
# Speech content/identity and recording context are not non-speech events.
EXCLUDED = {'Speech', 'Male speech, man speaking', 'Female speech, woman speaking',
            'Child speech, kid speaking', 'Conversation', 'Narration, monologue',
            'Babbling', 'Speech synthesizer', 'Whispering', 'Hubbub, speech noise',
            'Chatter', 'Silence'}


def select_events(scores, labels, start_ms, end_ms, threshold=0.1, top_k=5):
    selected = sorted(((float(score), int(index), label) for index, label in labels.items()
                       if label not in EXCLUDED and float(score := scores[int(index)]) >= threshold),
                      key=lambda value: (-value[0], value[1]))[:top_k]
    return [{'label': label, 'kind': 'audio-event', 'start_ms': start_ms, 'end_ms': end_ms,
             'temporal_resolution': 'analysis-window', 'confidence': round(score, 6)}
            for score, _, label in selected]


def analysis_windows(waveform, sample_rate, window_seconds):
    """Pad only the feature input; retain the source's real millisecond bounds.

    Kaldi filterbanks require one25ms frame before the extractor's usual
    fixed-length padding. A short final fragment must not fail earlier windows.
    Sub-millisecond fragments without a representable interval are omitted.
    """
    import numpy as np
    window = max(1, round(window_seconds * sample_rate))
    minimum = round(0.025 * sample_rate)
    for start in range(0, len(waveform), window):
        chunk = waveform[start:start + window]
        start_ms = round(start * 1000 / sample_rate)
        end_ms = round((start + len(chunk)) * 1000 / sample_rate)
        if end_ms <= start_ms:
            continue
        if len(chunk) < minimum:
            chunk = np.pad(chunk, (0, minimum - len(chunk)), mode='constant')
        yield chunk, start_ms, end_ms


class EventDetector:
    def __init__(self, threshold=0.1, top_k=5, window_seconds=10.0, threads=2):
        if not 0 <= threshold <= 1 or type(top_k) is not int or not 1 <= top_k <= 10:
            raise ValueError('invalid_event_selection')
        if not 1 <= window_seconds <= 10 or type(threads) is not int or not 1 <= threads <= 32:
            raise ValueError('invalid_event_window_or_threads')
        self.threshold, self.top_k, self.window_seconds, self.threads = threshold, top_k, window_seconds, threads
        self._lock = threading.Lock()
        self._model = self._extractor = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        try:
            from sonovect_assets import resolve, verify_identity
        except ModuleNotFoundError:
            from sonovect.assets import resolve, verify_identity
        root = os.getenv('SOUND_EVENT_MODEL_ROOT')
        if root:
            root = verify_identity(root, MODEL_ID, REVISION)
        else:
            root = resolve('ast-events', offline=os.getenv('SONOVECT_MODELS_OFFLINE', '1').lower() in {'1', 'true', 'yes'})
        extractor = AutoFeatureExtractor.from_pretrained(root, local_files_only=True, trust_remote_code=False)
        model = AutoModelForAudioClassification.from_pretrained(root, local_files_only=True,
                    use_safetensors=True, trust_remote_code=False).eval().to('cpu')
        self._extractor, self._model = extractor, model
        logging.getLogger(__name__).info('Loaded pinned AudioSet event model on CPU')

    def detect(self, waveform, sample_rate=16000):
        if sample_rate != 16000:
            raise ValueError('event_detector_requires_normalized_16khz_audio')
        # The classifier always assigns scores; digital zero is an exact control.
        if not len(waveform) or round(len(waveform) * 1000 / sample_rate) == 0 or not waveform.any():
            return []
        import torch
        with self._lock:
            self._load()
            events = []
            for chunk, start_ms, end_ms in analysis_windows(waveform, sample_rate, self.window_seconds):
                if not chunk.any():
                    continue
                inputs = self._extractor(chunk, sampling_rate=sample_rate, return_tensors='pt')
                with torch.inference_mode():
                    scores = self._model(**inputs).logits.sigmoid()[0]
                events.extend(select_events(scores, self._model.config.id2label,
                    start_ms, end_ms,
                    self.threshold, self.top_k))
            return events

    @property
    def engine(self):
        return {'model': MODEL_ID, 'revision': REVISION}
