"""Internal CPU-only, lazy optional voice analysis. No built-in speech detector."""
import asyncio
import io
import json
import os
import wave

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
import numpy as np
import torch
from typing import Annotated

from sonovect import __version__
from runtime_config import validate_environment
from vocal_detector import VocalDetector

validate_environment()
THREADS = int(os.getenv("VOCAL_THREADS", "2"))
torch.set_num_threads(THREADS)
detector = VocalDetector(THREADS, float(os.getenv("VOCAL_WINDOW_SECONDS", "10")))
app = FastAPI(title="Sonovect experimental CPU vocal worker", version=__version__)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "stage": "vocal", "device": "cpu",
            "model": detector.engine["model"], "revision": detector.engine["revision"],
            "model_loaded": detector.model is not None, "analysis_requests": detector.requests,
            "model_loads": detector.loads, "analysis_windows": detector.windows, "maturity": "experimental"}


@app.post("/internal/unload")
async def unload():
    await asyncio.to_thread(detector.unload)
    return {"status": "unloaded", "manager": {"resident": False, "busy": False}}


@app.post("/analyze")
async def analyze(files: Annotated[list[UploadFile], File()],
                  speech_context: Annotated[str, Form(max_length=1000000)],
                  measure: Annotated[bool, Form()] = False):
    try:
        contexts = json.loads(speech_context)
        if not isinstance(contexts, list) or not 1 <= len(files) <= 16 or len(contexts) != len(files):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "invalid_speech_context") from None
    if measure:
        raise HTTPException(422, "use_separate_measurements_stage")
    outputs = []
    for upload, context in zip(files, contexts):
        data = await upload.read(268435457)
        if len(data) > 268435456:
            raise HTTPException(413, "normalized_audio_limit")
        try:
            with wave.open(io.BytesIO(data), "rb") as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getcomptype()) != (16000, 1, 2, "NONE"):
                    raise ValueError()
                raw = w.readframes(w.getnframes())
                if not raw or len(raw) != w.getnframes() * 2:
                    raise ValueError()
                audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
            outputs.append(await asyncio.to_thread(detector.analyze, audio, context))
        except (ValueError, wave.Error, EOFError):
            raise HTTPException(422, "invalid_audio_or_speech_context") from None
        except Exception:
            raise HTTPException(503, "vocal_analysis_failed") from None
    return outputs[0] if len(outputs) == 1 else {"results": outputs}
