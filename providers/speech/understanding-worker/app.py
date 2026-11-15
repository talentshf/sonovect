"""Text-only Qwen Omni Thinker. Lazy, bounded, unloads after each request."""
import asyncio
import base64
import io
import math
import os
from pathlib import Path
import threading
import uuid
import wave
import numpy as np
import torch
from transformers import Qwen2_5OmniThinkerForConditionalGeneration
from audio_inputs import AudioInputs
from fastapi import FastAPI,HTTPException,Request
from gpu_capacity import wait_for_capacity
from gpu_release import release_idle_cuda
from failure_cleanup import detach_exception
from sonovect.assets import resolve
from sonovect import __version__

MODEL=os.getenv('OMNI_SERVED_MODEL','qwen2.5-omni')
CACHE=os.getenv('OMNI_MODEL_CACHE','/models/omni')
DEVICE=os.getenv('OMNI_DEVICE','cuda:0')
MAX_SECONDS=float(os.getenv('OMNI_MAX_SECONDS','60'))
if not math.isfinite(MAX_SECONDS) or not 0<MAX_SECONDS<=60 or DEVICE!='cuda:0':raise ValueError('invalid_omni_configuration')
REVISION='ae9e1690543ffd5c0221dc27f79834d0294cba00'
app=FastAPI(title='Sonovect audio understanding',version=__version__)
LOCK=threading.Lock()
MODEL_LOADED=False


def generate(audio,prompt,max_tokens):
    global MODEL_LOADED
    with LOCK:
        model=processor=inputs=output=None
        try:
            root=resolve('qwen-omni-7b',cache=CACHE,offline=True)
            wait_for_capacity(lambda:torch.cuda.mem_get_info(DEVICE),20*1024**3,timeout=30)
            model=Qwen2_5OmniThinkerForConditionalGeneration.from_pretrained(root,local_files_only=True,trust_remote_code=False,
                dtype=torch.bfloat16,device_map=DEVICE,attn_implementation='sdpa').eval()
            MODEL_LOADED=True
            processor=AudioInputs(root)
            conversation=[{'role':'system','content':[{'type':'text','text':'You are a helpful assistant. Answer using audible evidence. If uncertain, say so. Do not invent sounds or timestamps.'}]},
                {'role':'user','content':[{'type':'audio','audio':'local-input'},{'type':'text','text':prompt}]}]
            inputs={key:value.to(DEVICE) for key,value in processor.encode(audio,conversation).items()}
            for key in ('input_features','pixel_values'):
                if key in inputs:inputs[key]=inputs[key].to(model.dtype)
            with torch.inference_mode():output=model.generate(**inputs,max_new_tokens=max_tokens,do_sample=False,use_cache=True,
                eos_token_id=[processor.tokenizer.eos_token_id,processor.tokenizer.convert_tokens_to_ids("<|im_end|>")],pad_token_id=processor.tokenizer.pad_token_id)
            count=inputs['input_ids'].shape[1]
            answer=processor.tokenizer.batch_decode(output[:,count:],skip_special_tokens=True,clean_up_tokenization_spaces=False)[0]
            if not answer.strip():raise ValueError('empty_answer')
            return answer,{'prompt_tokens':count,'completion_tokens':output.shape[1]-count,'total_tokens':output.shape[1],'_finish_reason':'stop' if int(output[0,-1]) in {processor.tokenizer.eos_token_id,processor.tokenizer.convert_tokens_to_ids('<|im_end|>')} else 'length'}
        except Exception as error:
            detach_exception(error)
            raise RuntimeError("audio_model_failed") from None
        finally:
            model=processor=inputs=output=None
            MODEL_LOADED=False
            release_idle_cuda(torch,DEVICE)


@app.get('/health')
def health():return {'status':'ok','version':__version__,'model':MODEL,'model_revision':REVISION,'resident':MODEL_LOADED,'output':'text'}


@app.post('/v1/chat/completions')
async def completion(request:Request):
    if int(request.headers.get('content-length','0'))>5000000:raise HTTPException(413,'audio_limit')
    try:
        value=await request.json()
        if value.get('model')!=MODEL or value.get('stream',False) or value.get('temperature',0)!=0:raise ValueError()
        messages=value['messages']
        if len(messages)!=1 or messages[0]['role']!='user':raise ValueError()
        parts=messages[0]['content'];texts=[x['text'] for x in parts if x['type']=='text'];audios=[x['input_audio'] for x in parts if x['type']=='input_audio']
        if len(audios)!=1 or len(texts)!=1 or len(parts)!=2 or audios[0]['format']!='wav':raise ValueError()
        prompt=texts[0]
        if not isinstance(prompt,str) or not 1<=len(prompt)<=12000:raise ValueError()
        raw=base64.b64decode(audios[0]['data'],validate=True)
        with wave.open(io.BytesIO(raw),'rb') as wav:
            if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth(),wav.getcomptype())!=(16000,1,2,'NONE'):raise ValueError()
            if not 1600<=wav.getnframes()<=MAX_SECONDS*16000:raise ValueError()
            audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
        tokens=value.get('max_tokens',512)
        if type(tokens) is not int or not 1<=tokens<=768:raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,EOFError,wave.Error):raise HTTPException(400,'invalid_audio_question') from None
    try:answer,usage=await asyncio.to_thread(generate,audio,prompt,tokens)
    except Exception:raise HTTPException(503,'audio_model_failed') from None
    finish=usage.pop('_finish_reason')
    return {'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':0,'model':MODEL,
        'sonovect':{'engine':{'model':'Qwen/Qwen2.5-Omni-7B','revision':REVISION}},
        'choices':[{'index':0,'message':{'role':'assistant','content':answer},'finish_reason':finish}],'usage':usage}
