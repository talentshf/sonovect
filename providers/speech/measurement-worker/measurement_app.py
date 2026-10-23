"""Private normalized-audio endpoint for independent, weight-free measurements."""
import asyncio
import io
import json
import os
import wave
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from runtime_config import validate_environment
from sonovect import __version__
from sonovect.voice_measurements import MeasurementDetector, ENGINE

validate_environment()
THREADS = int(os.getenv("MEASUREMENT_THREADS", "2"))
os.environ["NUMBA_NUM_THREADS"] = str(THREADS)
detector = MeasurementDetector(float(os.getenv("MEASUREMENT_WINDOW_SECONDS", "10")))
app = FastAPI(title="Sonovect weight-free voice measurements", version=__version__)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "stage": "measurements", "device": "cpu",
            "engine": ENGINE, "model_weights": False, "analysis_requests": detector.requests,
            "analysis_windows": detector.windows}


@app.post("/analyze")
async def analyze(files: Annotated[list[UploadFile], File()],
                  speech_context: Annotated[str, Form(max_length=1000000)]):
    try:
        contexts = json.loads(speech_context)
        if not isinstance(contexts, list) or not 1 <= len(files) <= 16 or len(contexts) != len(files):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "invalid_speech_context") from None
    outputs = []
    for upload, context in zip(files, contexts):
        data = await upload.read(268435457)
        if len(data) > 268435456:
            raise HTTPException(413, "normalized_audio_limit")
        try:
            import numpy as np
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
            raise HTTPException(503, "measurement_analysis_failed") from None
    return outputs[0] if len(outputs) == 1 else {"results": outputs}
