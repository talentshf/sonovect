"""Optional Wyoming LAN bridge using the upstream event/server library."""
import argparse
import asyncio
from functools import partial
from pathlib import Path
import tempfile
import time
import wave


class BoundedReader:
    def __init__(self,reader,limit):self.reader,self.limit=reader,limit
    async def readline(self):
        line=await self.reader.readline()
        if len(line)>8192:raise ValueError("wyoming_header_limit")
        return line
    async def readexactly(self,size):
        if not 0<=size<=self.limit:raise ValueError("wyoming_payload_limit")
        return await self.reader.readexactly(size)
    def feed_eof(self):self.reader.feed_eof()


def handler_type():
    from wyoming.asr import Transcribe,Transcript
    from wyoming.audio import AudioStart,AudioChunk,AudioStop
    from wyoming.error import Error
    from wyoming.info import AsrModel,AsrProgram,Attribution,Describe,Info
    from wyoming.server import AsyncEventHandler
    from . import __version__

    class Handler(AsyncEventHandler):
        def __init__(self,reader,writer,*,client,model,max_seconds=60,slots=None,languages=None):
            super().__init__(BoundedReader(reader,max_seconds*48000*2),writer)
            self.client,self.model,self.limit=client,model,max_seconds
            self.slots=slots
            self.languages=languages or []
            self.buffer=bytearray();self.format=None;self.language=None;self.started=None
            self.names=[]

        async def handle_event(self,event):
            try:
                if Describe.is_type(event.type):
                    attribution=Attribution('Sonovect','https://github.com/talentshf/sonovect')
                    artifact=dict(name=self.model,attribution=attribution,installed=True,description='Shared Sonovect speech model',version=__version__)
                    await self.write_event(Info(asr=[AsrProgram(**artifact,models=[AsrModel(**artifact,languages=self.languages)],requires_external_vad=True)]).event())
                elif Transcribe.is_type(event.type):
                    value=Transcribe.from_event(event)
                    if value.name not in {None,self.model}:raise ValueError('model_not_available')
                    if value.context or value.vad_sensitivity:raise ValueError('unsupported_transcription_option')
                    self.language=value.language.replace("_","-").split("-")[0].lower() if value.language and value.language!="auto" else None
                    self.names=(value.transcript_names or [])+(value.transcript_terms or [])
                    if len(self.names)>200:raise ValueError('too_many_terms')
                    self.started=time.monotonic();self.buffer.clear();self.format=None
                elif AudioStart.is_type(event.type):
                    value=AudioStart.from_event(event)
                    if (value.width,value.channels)!=(2,1) or value.rate not in {8000,16000,24000,48000}:raise ValueError('pcm16_mono_required')
                    if self.started is None:self.started=time.monotonic()
                    self.format=value
                elif AudioChunk.is_type(event.type):
                    chunk=AudioChunk.from_event(event)
                    if self.format is None or (chunk.rate,chunk.width,chunk.channels)!=(self.format.rate,2,1):raise ValueError('audio_start_required_or_format_changed')
                    if len(chunk.audio)%2 or len(self.buffer)+len(chunk.audio)>self.limit*self.format.rate*2:raise ValueError('audio_duration_limit')
                    self.buffer.extend(chunk.audio)
                elif AudioStop.is_type(event.type):
                    if self.format is None or len(self.buffer)<self.format.rate//5:raise ValueError('audio_too_short')
                    if self.slots and self.slots.locked():raise ValueError('bridge_busy')
                    if self.slots:await self.slots.acquire()
                    try:
                        with tempfile.TemporaryDirectory(prefix='wyoming-') as folder:
                            path=Path(folder)/'audio.wav'
                            with wave.open(str(path),'wb') as out:
                                out.setparams((1,2,self.format.rate,0,'NONE','not compressed'));out.writeframes(self.buffer)
                            path.chmod(0o600)
                            task=asyncio.create_task(asyncio.to_thread(self.client.transcribe,path,model=self.model,language=self.language,prompt='Vocabulary: '+', '.join(self.names) if self.names else ''))
                            try:result=await asyncio.shield(task)
                            finally:
                                if not task.done():
                                    try:await asyncio.shield(task)
                                    except Exception:pass
                        await self.write_event(Transcript(text=result['text']).event())
                        self.buffer.clear();self.format=None;self.started=None
                    finally:
                        if self.slots:self.slots.release()
                return True
            except Exception:
                await self.write_event(Error('Speech request failed; inspect the Sonovect service','transcription_failed').event())
                return False

        async def run(self):
            try:await asyncio.wait_for(super().run(),600)
            except (TimeoutError,ConnectionError,ValueError):self.writer.close()
    return Handler


async def serve(uri,model,max_seconds):
    from wyoming.server import AsyncServer
    from .client import Client
    client=Client()
    try:
        capability=await asyncio.to_thread(lambda:client.request("GET","/v1/capabilities").json())
        languages=capability.get("speech_limits",{}).get("languages",[])
        await AsyncServer.from_uri(uri).run(partial(handler_type(),client=client,model=model,max_seconds=max_seconds,slots=asyncio.Semaphore(4),languages=languages))
    finally:client.close()


def main():
    parser=argparse.ArgumentParser(description='Optional LAN-only Wyoming ASR bridge; upstream protocol has no authentication')
    parser.add_argument('--uri',default='tcp://127.0.0.1:10300')
    parser.add_argument('--model',default='qwen3-asr')
    parser.add_argument('--max-seconds',type=int,default=60)
    args=parser.parse_args()
    if not 1<=args.max_seconds<=300:parser.error('max-seconds must be between 1 and 300')
    asyncio.run(serve(args.uri,args.model,args.max_seconds))


if __name__=='__main__':main()
