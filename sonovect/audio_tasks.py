"""Optional audio tasks run on the already normalized input, never a transcript."""
import base64
import httpx
from .upstreams import chat


def classify(settings,path,top_k):
    from .models import ClassScore
    with path.open('rb') as audio,httpx.Client(timeout=settings.provider_timeout,trust_env=False) as client:
        response=client.post(settings.sound_url+'/classify',params={'top_k':top_k},files={'file':('audio.wav',audio,'audio/wav')})
        response.raise_for_status();value=response.json()
    scores=[ClassScore.model_validate(x).model_dump() for x in value['scores']]
    if not scores or len(scores)>top_k:raise ValueError('classification_result_invalid')
    return {**value,'scores':scores}


def understand(settings,path,question,duration_ms):
    if duration_ms>settings.understanding_max_seconds*1000:
        raise ValueError('understanding_duration_exceeded')
    request=chat(settings,'understanding',[{'role':'user','content':[
        {'type':'text','text':question},{'type':'input_audio','input_audio':{
            'format':'wav','data':base64.b64encode(path.read_bytes()).decode()}}]}],max_tokens=512)
    with httpx.Client(timeout=settings.provider_timeout,trust_env=False) as client:
        response=client.post(request['url'],headers=request['headers'],json=request['body'])
        response.raise_for_status();value=response.json()
    choice=value['choices'][0]
    if choice.get('finish_reason') not in {'stop','length'}:raise ValueError('understanding_finish_reason_unavailable')
    text=choice['message']['content']
    if not isinstance(text,str) or not text.strip():raise ValueError('understanding_result_invalid')
    engine=(value.get('sonovect') or {}).get('engine')
    if engine:
        from .models import ModelIdentity
        engine=ModelIdentity.model_validate(engine).model_dump()
    return {'text':text,'model':settings.understanding_model,'identity_source':'engine-response' if engine else 'operator-configuration',**({'engine':engine} if engine else {}),
            'input':'audio','requires_review':True,'finish_reason':choice['finish_reason'],**({'usage':value['usage']} if value.get('usage') else {})}


def align(settings,path,text,language):
    from .models import Alignment
    from .upstreams import provider_headers
    with path.open('rb') as audio,httpx.Client(timeout=settings.provider_timeout,trust_env=False,headers=provider_headers(settings)) as client:
        response=client.post(settings.provider_url+'/align',data={'text':text,'language':language},files={'file':('audio.wav',audio,'audio/wav')})
        response.raise_for_status()
        return Alignment.model_validate(response.json()).model_dump()


def run(settings,path,metadata,options,previous,current,on_stage=None):
    from .worker import merge_analysis
    result=merge_analysis(previous,current)
    for name,enabled,fn in [
        ('alignment',options.get('alignment_text'),lambda:align(settings,path,options['alignment_text'],options['language'])),
        ('classification',options.get('classify_audio'),lambda:classify(settings,path,options.get('classify_top_k',5))),
        ('understanding',options.get('audio_question'),lambda:understand(settings,path,options['audio_question'],metadata['duration_ms']))]:
        if not enabled or result.get('stages',{}).get(name,{}).get('status')=='completed':continue
        try:
            value=fn()
            result[name]=value
            result.setdefault('stages',{})[name]={'status':'completed'}
        except Exception:
            result.setdefault('stages',{})[name]={'status':'failed','error':name+'_failed'}
        if on_stage:on_stage(merge_analysis({},result),name)
    return merge_analysis({},result)
