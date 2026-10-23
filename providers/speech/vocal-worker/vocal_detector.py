"""Optional CPU emotion classification. Speech detection belongs to the ASR lane."""
import gc
import json
import os
from pathlib import Path
import threading

import numpy as np

from sonovect.assets import catalog, resolve, verify
from sonovect.vocal_context import regions_from_context

LABELS = {"angry": "ANGRY", "disgusted": "DISGUSTED", "fearful": "FEARFUL",
          "happy": "HAPPY", "neutral": "NEUTRAL", "sad": "SAD", "surprised": "SURPRISED"}


class VocalDetector:
    def __init__(self, threads=2, window_seconds=10):
        self.threads = threads
        self.window_ms = int(window_seconds * 1000)
        self.model = None
        self.lock = threading.Lock()
        self.requests = self.windows = self.loads = 0
        self.identity = catalog()["emotion2vec-base"]
        self.engine = {"model": self.identity["repo_id"], "revision": self.identity["revision"]}

    def unload(self):
        with self.lock:
            self.model = None
            gc.collect()

    def load(self):
        if self.model is not None:
            return
        import torch
        from funasr import AutoModel
        from omegaconf import OmegaConf
        root = os.getenv("VOCAL_MODEL_ROOT", "")
        root = Path(verify(root, self.identity) if root else resolve(
            "emotion2vec-base", os.getenv("HF_HUB_CACHE"),
            offline=os.getenv("SONOVECT_MODELS_OFFLINE", "1").lower() in {"1", "true", "yes"}))
        cfg = OmegaConf.to_container(OmegaConf.load(root / "config.yaml"), resolve=True)
        for key, value in json.loads((root / "configuration.json").read_text()).get("file_path_metas", {}).items():
            if key == "config":
                continue
            if isinstance(value, dict):
                for name, path in value.items():
                    cfg.setdefault(key, {})[name] = str(root / path)
            else:
                cfg[key] = str(root / value)
        cfg.update(device="cpu", ncpu=self.threads, ngpu=0, disable_update=True,
                   disable_pbar=True, trust_remote_code=False, model_path=str(root),
                   init_param=str(root / "model.pt"), ignore_init_mismatch=False)
        candidate = AutoModel(**cfg)
        state = torch.load(root / "model.pt", map_location="cpu", weights_only=True)
        for group in ["state_dict", "model_state_dict", "model"]:
            if group in state:
                state = state[group]
        scopes = list(cfg.get("scope_map", [])) + ["module.", "None"]
        checked = 0
        for name, tensor in candidate.model.state_dict().items():
            selected = name
            for source, dest in zip(scopes[::2], scopes[1::2]):
                source = "" if source.lower() == "none" else source
                dest = "" if dest.lower() == "none" else dest
                key = source + name if not dest else name.replace(dest, source, 1) if name.startswith(dest) else None
                if key in state:
                    selected = key
            if selected not in state:
                if not name.startswith("modality_encoders.AUDIO.decoder."):
                    raise RuntimeError("vocal_inference_tensor_missing")
                continue
            if tensor.shape != state[selected].shape or not torch.equal(tensor.detach().cpu(), state[selected].to(tensor.dtype)):
                raise RuntimeError("vocal_inference_tensor_mismatch")
            checked += 1
        if checked != 185:
            raise RuntimeError("vocal_inference_tensor_count_mismatch")
        def forbid_decoder(module, inputs):
            raise RuntimeError("training_decoder_not_for_inference")
        candidate.model.modality_encoders["AUDIO"].decoder.register_forward_pre_hook(forbid_decoder)
        self.model = candidate
        self.loads += 1

    def analyze(self, audio, context):
        with self.lock:
            self.requests += 1
            duration_ms = round(len(audio) * 1000 / 16000)
            regions = regions_from_context(context, duration_ms)
            output = dict(engine=self.engine, duration_ms=duration_ms, parse_valid=True, vocal_valid=True,
                          emotions=[], voice=[], measurements=[], warnings=[], speech_gate="existing-vad",
                          emotion_scope="experimental-not-chinese-qualified")
            if not regions:
                output["warnings"] = ["no_usable_speech"]
                return output
            try:
                self.load()
                import torch
                for start in range(0, duration_ms, self.window_ms):
                    end = min(duration_ms, start + self.window_ms)
                    if not any(min(end, b) > max(start, a) for a, b in regions):
                        continue
                    window = np.asarray(audio[start * 16:end * 16], dtype=np.float32)
                    if not len(window):
                        continue
                    with torch.inference_mode():
                        raw = self.model.generate(input=window, key=["audio"], granularity="utterance",
                                                  extract_embedding=False, disable_pbar=True)[0]
                    labels, scores = raw["labels"], np.asarray(raw["scores"], dtype=np.float64)
                    if (len(labels) != 9 or scores.shape != (9,) or not np.isfinite(scores).all()
                            or np.any(scores < 0) or np.any(scores > 1)):
                        raise RuntimeError("invalid_vocal_scores")
                    selected = int(scores.argmax())
                    label = LABELS.get(str(labels[selected]).split("/")[-1].lower())
                    if label:
                        output["emotions"].append(dict(label=label, confidence=float(scores[selected]),
                            start_ms=start, end_ms=end, temporal_resolution="analysis-window"))
                    else:
                        output["warnings"].append("emotion_uncertain")
                    self.windows += 1
                output["warnings"] = sorted(set(output["warnings"]))
                return output
            except Exception:
                self.model = None
                gc.collect()
                raise
