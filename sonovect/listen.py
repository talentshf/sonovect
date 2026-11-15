"""Deepgram file/finalized PCM turns and FunASR offline WebSocket adapters."""
import asyncio
import hmac
import io
import json
from pathlib import Path
import tempfile
import time
import uuid
import wave
from fastapi import HTTPException,Request,WebSocket,WebSocketDisconnect
from fastapi.responses import JSONResponse,Response
from .audio_api import admit_bytes
from .backends import SpeechBackend
from .models import Options
from .waiting import await_job,job_headers
from .vad import NeuralTurns,scores as vad_scores


def pcm_wav(data,rate,channels=1):
    if not data or len(data)%2:raise ValueError('invalid_pcm_audio')
    result=io.BytesIO()
    with wave.open(result,'wb') as audio:
        audio.setparams((channels,2,rate,0,'NONE','not compressed'));audio.writeframes(data)
    return result.getvalue()


def authorized(ws,settings):
    values=ws.headers.getlist('authorization')
    scheme,_,value=values[0].partition(' ') if len(values)==1 else ('','','')
    return scheme.lower() in {'bearer','token'} and hmac.compare_digest(value.encode(),settings.token.encode())


def boolean(value):
    if value not in {'true','false'}:raise ValueError('boolean_required')
    return value=='true'


def parameters(query,settings,live=False):
    allowed={'model','language','diarize','punctuate','smart_format','detect_language','encoding','sample_rate','channels','multichannel'}
    if live:allowed|={'endpointing','interim_results','vad_events'}
    if set(query)-allowed:raise ValueError('unsupported_parameter')
    if query.get('model',settings.transcription_model)!=settings.transcription_model:raise ValueError('model_not_available')
    channels=int(query.get('channels','1'))
    if not 1<=channels<=8 or (live and (channels!=1 or query.get('multichannel','false')!='false')):raise ValueError('channel_configuration_not_supported')
    if any(boolean(query[k]) for k in ('punctuate','smart_format') if k in query):raise ValueError('optional_text_processing_not_supported')
    if query.get('detect_language') not in {None,'true'}:raise ValueError('automatic_language_detection_is_intrinsic')
    if live:
        if query.get('interim_results','false')!='false':raise ValueError('interim_results_not_available')
        endpoint=query.get('endpointing','300' if settings.realtime_vad_enabled else 'false')
        if endpoint!='false' and (not settings.realtime_vad_enabled or not endpoint.isdigit() or not 100<=int(endpoint)<=2000):raise ValueError('endpointing_not_supported')
        boolean(query.get('vad_events','false'))
    rate=int(query.get('sample_rate','16000'))
    if rate not in {8000,16000,24000,48000}:raise ValueError('sample_rate_not_supported')
    if live and query.get('encoding','linear16')!='linear16':raise ValueError('linear16_required')
    if not live and query.get('encoding') not in {None,'linear16'}:raise ValueError('encoding_not_supported')
    return Options(language=query.get('language'),speakers=boolean(query.get('diarize','false')),timestamps='word',channel_mode='independent' if boolean(query.get('multichannel','false')) else 'mix'),rate


def alternatives(transcript,evidence):
    words=[]
    for channel in evidence.get('transcripts',[]):
        for sentence in channel.get('sentences',[]):
            for word in sentence.get('words',[]):
                row={'word':word['text'],'start':word['begin_time']/1000,'end':word['end_time']/1000,'punctuated_word':word['text']}
                if 'speaker_id' in sentence:row['speaker']=sentence['speaker_id']
                words.append(row)
    if transcript['text'] and not words:raise ValueError('word_evidence_unavailable')
    # Qwen/aligner provide no calibrated confidence: those fields remain absent.
    return [{'transcript':transcript['text'],'words':words}]


def install(app,settings,store,admit,engine=None):
    engine=engine or SpeechBackend(settings)
    slots=getattr(app.state,'audio_slots',asyncio.Semaphore(settings.realtime_max_sessions))

    @app.post('/v1/listen')
    async def file(request:Request):
        try:options,rate=parameters(request.query_params,settings)
        except ValueError as error:raise HTTPException(400,str(error)) from None
        if request.headers.get('content-type','').startswith('application/json'):raise HTTPException(400,'remote_url_input_not_supported')
        data=await request.body()
        if request.query_params.get('encoding')=='linear16':
            try:data=pcm_wav(data,rate,int(request.query_params.get('channels','1')))
            except ValueError as error:raise HTTPException(400,str(error)) from None
        job_id=await admit_bytes(admit,data,options,request.headers.get('idempotency-key'))
        job=await await_job(request,settings,store,job_id)
        if isinstance(job,Response):return job
        if job['state']!='succeeded':raise HTTPException(503,'transcription_failed',headers=job_headers(job_id))
        try:
            if len(job['result'])!=len(job['evidence']):raise ValueError()
            values=[{'alternatives':alternatives(result,evidence)} for result,evidence in zip(job['result'],job['evidence'])]
        except (ValueError,KeyError,IndexError):raise HTTPException(422,'word_evidence_unavailable',headers=job_headers(job_id)) from None
        duration=job['sources'][0]['media']['duration_ms']/1000
        return JSONResponse({'metadata':{'request_id':job_id,'created':__import__('datetime').datetime.fromtimestamp(job['created'],__import__('datetime').timezone.utc).isoformat(),'duration':duration,'channels':len(values),'models':[settings.transcription_model]},
            'results':{'channels':values}},headers=job_headers(job_id))

    async def infer(data,rate,options):
        with tempfile.TemporaryDirectory(prefix='listen-',dir=settings.data_dir) as folder:
            path=Path(folder)/'audio.wav';path.write_bytes(pcm_wav(data,rate));path.chmod(0o600)
            task=asyncio.create_task(asyncio.to_thread(engine.process,path,'audio',options.wire()))
            try:return await asyncio.shield(task)
            finally:
                if not task.done():
                    try:await asyncio.shield(task)
                    except Exception:pass

    async def open_socket(ws):
        if not settings.realtime_enabled or not authorized(ws,settings):await ws.close(code=1008);return False
        await ws.accept()
        if slots.locked():await ws.close(code=1013,reason='realtime_busy');return False
        await slots.acquire();return True

    @app.websocket('/v1/listen')
    async def live(ws:WebSocket):
        if not await open_socket(ws):return
        buffer=bytearray();started=time.monotonic();offset=0
        try:
            options,rate=parameters(ws.query_params,settings,live=True)
            endpoint=ws.query_params.get('endpointing','300' if settings.realtime_vad_enabled else 'false')
            detector=NeuralTurns(rate,{'threshold':.5,'prefix_padding_ms':300,'silence_duration_ms':int(endpoint)},settings.realtime_max_turn_seconds) if endpoint!='false' else None
            async def emit_result(pcm,start,last=False,finalized=False):
                nonlocal offset
                if not pcm:return
                duration=len(pcm)/(2*rate)
                result=await infer(pcm,rate,options)
                channel={'alternatives':alternatives(result.transcript,result.evidence)}
                for word in channel['alternatives'][0]['words']:
                    word['start']+=start;word['end']+=start
                await ws.send_json({'type':'Results','channel_index':[0,1],'start':start,'duration':duration,
                    'is_final':True,'speech_final':last,'from_finalize':finalized,'channel':channel})
                offset=start+duration
            async def finalize(last=False):
                if detector:
                    await emit_result(bytes(detector.buffer),detector.origin/rate,last,True);detector.clear()
                else:
                    await emit_result(bytes(buffer),offset,last,True);buffer.clear()
            while time.monotonic()-started<settings.realtime_max_seconds:
                message=await asyncio.wait_for(ws.receive(),settings.realtime_idle_seconds)
                if message['type']=='websocket.disconnect':break
                if message.get('bytes') is not None:
                    data=message['bytes']
                    if len(data)%2 or not data or len(data)>192000:raise ValueError('invalid_pcm_frame')
                    if detector:
                        if detector.total+len(data)//2>settings.realtime_max_seconds*rate:raise ValueError('session_audio_limit')
                        for event in await detector.feed(data,lambda pcm,fs:vad_scores(settings,pcm,fs)):
                            if event[0]=='started' and boolean(ws.query_params.get('vad_events','false')):
                                await ws.send_json({'type':'SpeechStarted','channel':[0],'timestamp':event[1]/1000})
                            elif event[0]=='stopped':await emit_result(event[2],event[3]/1000,True)
                        if len(detector.buffer)>settings.realtime_max_turn_seconds*rate*2:await finalize(True)
                    else:
                        if len(buffer)+len(data)>settings.realtime_max_turn_seconds*rate*2:raise ValueError('finalize_before_turn_limit')
                        buffer.extend(data)
                else:
                    value=json.loads(message.get('text',''))
                    if value.get('type')=='KeepAlive':continue
                    if value.get('type')=='Finalize':await finalize(True)
                    elif value.get('type')=='CloseStream':
                        await finalize(True)
                        await ws.send_json({'type':'Metadata','request_id':uuid.uuid4().hex,'duration':detector.total/rate if detector else offset,'channels':1});break
                    else:raise ValueError('unsupported_event')
        except (WebSocketDisconnect,RuntimeError):pass
        except Exception:
            try:await ws.send_json({'type':'Error','description':'listen_request_failed','code':'listen_request_failed'})
            except (WebSocketDisconnect,RuntimeError):pass
        finally:
            slots.release()
            try:await ws.close()
            except RuntimeError:pass

    @app.websocket('/v1/funasr')
    async def funasr(ws:WebSocket):
        if not await open_socket(ws):return
        buffer=bytearray();started=time.monotonic();config=None
        try:
            while time.monotonic()-started<settings.realtime_max_seconds:
                message=await asyncio.wait_for(ws.receive(),settings.realtime_idle_seconds)
                if message['type']=='websocket.disconnect':break
                if message.get('bytes') is not None:
                    if config is None:raise ValueError('send_configuration_first')
                    data=message['bytes']
                    if not data or len(data)%2 or len(data)>192000:raise ValueError('invalid_pcm_frame')
                    if len(buffer)+len(data)>settings.realtime_max_turn_seconds*config['audio_fs']*2:raise ValueError('turn_limit_exceeded')
                    buffer.extend(data);continue
                value=json.loads(message.get('text',''))
                if not isinstance(value,dict):raise ValueError('invalid_configuration')
                if config is None:
                    if set(value)-{'mode','wav_name','wav_format','is_speaking','audio_fs','hotwords','itn'} or value.get('mode','offline')!='offline' or value.get('wav_format','pcm')!='pcm':
                        raise ValueError('offline_pcm_mode_required')
                    if value.get('itn',True) is not True:raise ValueError('itn_false_not_supported')
                    rate=value.get('audio_fs',16000)
                    if rate not in {8000,16000}:raise ValueError('sample_rate_not_supported')
                    hotwords=value.get('hotwords','{}')
                    hotwords=json.loads(hotwords) if isinstance(hotwords,str) else hotwords
                    if not isinstance(hotwords,dict) or any(type(v) not in {float,int} for v in hotwords.values()):raise ValueError('invalid_hotwords')
                    if any(v!=0 for v in hotwords.values()):raise ValueError('weighted_hotwords_not_supported')
                    config={**value,'audio_fs':rate,'options':Options(hotwords=list(hotwords))}
                if value.get('is_speaking') is False:
                    if not buffer:raise ValueError('empty_audio')
                    result=await infer(bytes(buffer),config['audio_fs'],config['options'])
                    await ws.send_json({'mode':'offline','wav_name':config.get('wav_name','audio'),'text':result.transcript['text'],'is_final':False})
                    buffer.clear();config=None
        except (WebSocketDisconnect,RuntimeError):pass
        except Exception:
            try:await ws.send_json({'error':'funasr_request_failed','supported_mode':'offline'})
            except (WebSocketDisconnect,RuntimeError):pass
        finally:
            slots.release()
            try:await ws.close()
            except RuntimeError:pass
