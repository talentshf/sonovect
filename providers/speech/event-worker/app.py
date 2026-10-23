import asyncio,io,os,wave
import numpy as np
import torch
from fastapi import FastAPI,File,HTTPException,UploadFile
from typing import Annotated
from event_detector import EventDetector
from sonovect_version import VERSION
from runtime_config import validate_environment
validate_environment()
THREADS=int(os.getenv("SOUND_EVENT_THREADS","2"));torch.set_num_threads(THREADS)
detector=EventDetector(float(os.getenv("SOUND_EVENT_THRESHOLD","0.1")),int(os.getenv("SOUND_EVENT_TOP_K","5")),float(os.getenv("SOUND_EVENT_WINDOW_SECONDS","10")),THREADS)
app=FastAPI(title="Sonovect AST event worker",version=VERSION)
REQUESTS=0
@app.get("/health")
def health():
 return {"status":"ok","version":VERSION,"stage":"events","device":"cpu","model":detector.engine["model"],"revision":detector.engine["revision"],"model_loaded":detector._model is not None,"analysis_requests":REQUESTS}
@app.post("/analyze")
async def analyze(files:Annotated[list[UploadFile],File()]):
 global REQUESTS
 REQUESTS+=1
 outputs=[]
 for upload in files:
  data=await upload.read(268435457)
  if len(data)>268435456:raise HTTPException(413,"normalized_audio_limit")
  try:
   with wave.open(io.BytesIO(data),"rb") as w:
    if (w.getframerate(),w.getnchannels(),w.getsampwidth(),w.getcomptype())!=(16000,1,2,"NONE"):raise ValueError()
    audio=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").astype(np.float32)/32768.0
  except (ValueError,wave.Error,EOFError):raise HTTPException(422,"normalized_pcm16_wav_required") from None
  events=await asyncio.to_thread(detector.detect,audio,16000)
  outputs.append({"engine":detector.engine,"duration_ms":round(len(audio)*1000/16000),"events":events,"parse_valid":True,"events_valid":True})
 return outputs[0] if len(outputs)==1 else {"results":outputs}
