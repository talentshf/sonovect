"""Audio-input Chat Completions and HF audio classification contracts."""
import base64
import binascii
import io
import json
import time
import uuid
from fastapi import Depends,HTTPException,Request,UploadFile
from fastapi.responses import JSONResponse,Response
from .models import Options
from .waiting import await_job,job_headers


async def admit_bytes(admit,data,options,idempotency_key=None):
    if not data:raise HTTPException(400,'empty_audio')
    response=await admit(files=[UploadFile(file=io.BytesIO(data),filename='audio')],
                         options=options.model_dump_json(),idempotency_key=idempotency_key)
    return json.loads(response.body)['id']


def decode(value):
    try:
        if not isinstance(value,str):raise ValueError()
        return base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise HTTPException(400,'invalid_base64_audio') from None


def install(app,settings,store,authenticate,admit):
    @app.post('/models/ast-audioset',dependencies=[Depends(authenticate)])
    async def classification(request:Request):
        if not (settings.sound_enabled and settings.sound_url):raise HTTPException(400,'classification_not_configured')
        top_k=5
        if request.headers.get('content-type','').split(';')[0]=='application/json':
            try:value=await request.json()
            except ValueError:raise HTTPException(400,'invalid_json') from None
            if not isinstance(value,dict) or set(value)-{'inputs','parameters'}:raise HTTPException(400,'unsupported_parameter')
            parameters=value.get('parameters') or {}
            if not isinstance(parameters,dict) or set(parameters)-{'top_k'}:raise HTTPException(400,'unsupported_parameter')
            top_k=parameters.get('top_k',5)
            data=decode(value.get('inputs'))
        else:data=await request.body()
        if type(top_k) is not int or not 1<=top_k<=527:raise HTTPException(400,'invalid_top_k')
        if len(data)>settings.max_upload_bytes:raise HTTPException(413,'upload_limit_exceeded')
        job_id=await admit_bytes(admit,data,Options(transcribe=False,classify_audio=True,classify_top_k=top_k),request.headers.get('idempotency-key'))
        job=await await_job(request,settings,store,job_id,'classification')
        if isinstance(job,Response):return job
        value=(job['analysis'] or [{}])[0]
        if job['state']!='succeeded' or not value.get('classification'):raise HTTPException(503,'classification_failed',headers=job_headers(job_id))
        result=JSONResponse(value['classification']['scores'],headers=job_headers(job_id))
        result.headers['X-Sonovect-Aggregation']=value['classification']['aggregation']
        return result

    @app.post('/v1/chat/completions',dependencies=[Depends(authenticate)])
    async def understand(request:Request):
        if not settings.understanding_url:raise HTTPException(400,'understanding_not_configured')
        try:value=await request.json()
        except ValueError:raise HTTPException(400,'invalid_json') from None
        if not isinstance(value,dict) or set(value)-{'model','messages','modalities','stream','temperature','max_tokens'}:
            raise HTTPException(400,'unsupported_parameter')
        if value.get('model')!=settings.understanding_model:raise HTTPException(400,'model_not_available')
        if value.get('modalities',['text'])!=['text'] or value.get('stream',False) is not False:
            raise HTTPException(400,'text_output_non_streaming_required')
        if value.get('temperature',0)!=0 or 'max_tokens' in value:raise HTTPException(400,'generation_parameter_not_supported')
        messages=value.get('messages')
        if not isinstance(messages,list) or len(messages)!=1 or not isinstance(messages[0],dict) or messages[0].get('role')!='user':
            raise HTTPException(400,'one_audio_user_message_required')
        content=messages[0].get('content')
        if not isinstance(content,list):raise HTTPException(400,'audio_content_required')
        texts=[];audio=None
        for item in content:
            if not isinstance(item,dict):raise HTTPException(400,'invalid_content')
            if item.get('type')=='text' and set(item)=={'type','text'} and isinstance(item['text'],str):texts.append(item['text'])
            elif item.get('type')=='input_audio' and set(item)=={'type','input_audio'} and audio is None:
                source=item['input_audio']
                if not isinstance(source,dict) or set(source)!={'data','format'} or source.get('format') not in {'wav','mp3'}:
                    raise HTTPException(400,'unsupported_audio_format')
                audio=decode(source['data'])
            else:raise HTTPException(400,'unsupported_content')
        question='\n'.join(texts).strip()
        if audio is None or not question or len(question)>12000:raise HTTPException(400,'audio_and_question_required')
        if len(audio)>settings.max_upload_bytes:raise HTTPException(413,'upload_limit_exceeded')
        job_id=await admit_bytes(admit,audio,Options(transcribe=False,audio_question=question),request.headers.get('idempotency-key'))
        job=await await_job(request,settings,store,job_id,'understanding')
        if isinstance(job,Response):return job
        result=(job['analysis'] or [{}])[0].get('understanding')
        if job['state']!='succeeded' or not result:raise HTTPException(503,'understanding_failed',headers=job_headers(job_id))
        return JSONResponse({'id':'chatcmpl-'+job_id,'object':'chat.completion','created':int(job['created']),
            'model':settings.understanding_model,'choices':[{'index':0,'message':{'role':'assistant','content':result['text']},'finish_reason':result.get('finish_reason','stop')}],**({'usage':result['usage']} if result.get('usage') else {})},headers=job_headers(job_id))
