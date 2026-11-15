"""Neural speech endpoints over a bounded rolling window; no RMS heuristics."""
import io
import math
import wave
import httpx


def turn_detection(value,settings):
    if value is None:return None
    if not settings.realtime_vad_enabled or not isinstance(value,dict) or value.get('type')!='server_vad':
        raise ValueError('server_vad_not_configured')
    if set(value)-{'type','threshold','prefix_padding_ms','silence_duration_ms','create_response','interrupt_response'}:
        raise ValueError('unsupported_turn_detection_parameter')
    if value.get('create_response',False) or value.get('interrupt_response',False):raise ValueError('transcription_only_session')
    threshold=value.get('threshold',.5);prefix=value.get('prefix_padding_ms',300);silence=value.get('silence_duration_ms',500)
    if type(threshold) not in {int,float} or not math.isfinite(threshold) or not 0<=threshold<=1:
        raise ValueError('invalid_vad_threshold')
    if type(prefix) is not int or not 0<=prefix<=1000 or type(silence) is not int or not 100<=silence<=2000:
        raise ValueError('invalid_vad_padding_or_silence')
    return {'type':'server_vad','threshold':threshold,'prefix_padding_ms':prefix,'silence_duration_ms':silence}


async def scores(settings,pcm,rate):
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setparams((1,2,rate,0,'NONE','not compressed'));wav.writeframes(pcm)
    from .upstreams import provider_headers
    try:
        async with httpx.AsyncClient(timeout=10,trust_env=False,headers=provider_headers(settings)) as client:
            response=await client.post(settings.provider_url+'/vad/scores',files={'file':('window.wav',output.getvalue(),'audio/wav')})
            response.raise_for_status();value=response.json()
    except (httpx.HTTPError,ValueError):
        raise ValueError("vad_unavailable") from None
    values=value['probabilities']
    if value.get('frame_shift_ms')!=10 or not isinstance(values,list) or not values or len(values)>505 or any(type(x) not in {int,float} or not math.isfinite(x) or not 0<=x<=1 for x in values):
        raise ValueError('invalid_vad_result')
    return values


class NeuralTurns:
    def __init__(self,rate,configuration,max_seconds=60):
        self.limit=round(max_seconds*rate)*2
        self.rate=rate;self.options=configuration;self.buffer=bytearray()
        self.origin=0;self.total=0;self.checked=0;self.start=None;self.last=None

    def clear(self):
        self.buffer.clear();self.origin=self.total;self.start=self.last=None;self.checked=self.total

    async def feed(self,pcm,score):
        events=[];step=self.rate//2  # 250ms of PCM16
        for offset in range(0,len(pcm),step):
            chunk=pcm[offset:offset+step];self.buffer.extend(chunk);self.total+=len(chunk)//2
            if self.total-self.checked<self.rate//4:continue
            self.checked=self.total
            window=bytes(self.buffer[-self.rate*4:])  # <=2s, independent of turn length
            if len(window)<self.rate//5:continue
            probabilities=await score(window,self.rate)
            window_start=self.total-len(window)//2
            hits=[(window_start+round(i*self.rate/100),window_start+round((i+1)*self.rate/100))
                  for i,p in enumerate(probabilities) if p>=self.options['threshold'] and window_start+round((i+1)*self.rate/100)>self.origin]
            # Require 100ms contiguous positive evidence before starting a turn.
            runs=[]
            for first,last in hits:
                if runs and first<=runs[-1][1]:runs[-1]=(runs[-1][0],last)
                else:runs.append((first,last))
            stable=[x for x in runs if x[1]-x[0]>=self.rate//10]
            if self.start is None and stable:
                self.start=max(self.origin,stable[0][0]-round(self.options['prefix_padding_ms']*self.rate/1000))
                cut=(self.start-self.origin)*2
                del self.buffer[:cut];self.origin=self.start
                events.append(('started',round(self.start*1000/self.rate)))
            if self.start is not None:
                relevant=[last for first,last in hits if last>self.start]
                if relevant:self.last=max(self.last or 0,max(relevant))
                end=(self.last or self.total)+round(self.options['silence_duration_ms']*self.rate/1000)
                if self.total>=end:
                    size=(end-self.origin)*2;audio=bytes(self.buffer[:size]);del self.buffer[:size]
                    events.append(('stopped',round(end*1000/self.rate),audio,round(self.origin*1000/self.rate)))
                    self.origin=end;self.start=self.last=None
            if self.start is not None and len(self.buffer)>=self.limit:
                end=self.origin+self.limit//2
                events.append(('stopped',round(end*1000/self.rate),bytes(self.buffer[:self.limit]),round(self.origin*1000/self.rate)))
                del self.buffer[:self.limit];self.origin=end;self.start=self.last=None
            elif self.start is None and len(self.buffer)>self.rate*4:
                cut=len(self.buffer)-self.rate*4;del self.buffer[:cut];self.origin+=cut//2
        return events
