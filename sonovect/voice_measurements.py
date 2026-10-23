"""Weight-free acoustic measurements; never imports an emotion or speech model."""
import math
import threading
from .vocal_context import regions_from_context

ENGINE = {"model": "sonovect/pyin-pcm-rms", "revision": "1"}


def measurements(audio, start_ms, end_ms):
    import numpy as np
    import librosa
    rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
    energy = 20 * math.log10(rms) if rms > 0 else None
    pitch = None
    if len(audio) >= 2048:
        f0, voiced, _ = librosa.pyin(audio, fmin=50, fmax=600, sr=16000,
                                    frame_length=2048, hop_length=256)
        values = f0[np.asarray(voiced) & np.isfinite(f0)]
        pitch = float(np.median(values)) if len(values) else None
    return [dict(kind=kind, value=value, unit=unit, method=method,
                 status="measured" if value is not None else "unavailable",
                 start_ms=start_ms, end_ms=end_ms, temporal_resolution="analysis-window")
            for kind, value, unit, method in [("pitch", pitch, "Hz", "pyin-50-600hz"),
                                             ("relative-energy", energy, "dBFS", "pcm-rms")]]


class MeasurementDetector:
    def __init__(self, window_seconds=10):
        self.window_ms = int(window_seconds * 1000)
        self.lock = threading.Lock()
        self.requests = self.windows = 0

    def analyze(self, audio, context):
        with self.lock:
            self.requests += 1
            duration_ms = round(len(audio) * 1000 / 16000)
            regions = regions_from_context(context, duration_ms)
            output = dict(engine=ENGINE, duration_ms=duration_ms, parse_valid=True,
                          measurements_valid=True, measurements=[], warnings=[])
            if not regions:
                output["warnings"] = ["no_usable_speech"]
                return output
            for start in range(0, duration_ms, self.window_ms):
                end = min(duration_ms, start + self.window_ms)
                if not any(min(end, b) > max(start, a) for a, b in regions):
                    continue
                window = audio[start * 16:end * 16]
                if not len(window):
                    continue
                output["measurements"].extend(measurements(window, start, end))
                self.windows += 1
            return output
