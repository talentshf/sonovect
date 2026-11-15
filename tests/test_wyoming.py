import asyncio,functools,unittest,wave
from wyoming.asr import Transcribe,Transcript
from wyoming.audio import AudioStart,AudioChunk,AudioStop
from wyoming.client import AsyncClient
from wyoming.info import Describe,Info
from wyoming.error import Error
from wyoming.server import AsyncTcpServer
from sonovect.wyoming import handler_type

class Client:
    def __init__(self):self.calls=[]
    def transcribe(self,path,**options):
        with wave.open(str(path)) as audio:
            assert audio.getnframes()==1600
        self.calls.append(options)
        return {'text':'你好'}

class WyomingTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_wyoming_discovery_and_audio_turn(self):
        server=AsyncTcpServer('127.0.0.1',0);client=Client()
        await server.start(functools.partial(handler_type(),client=client,model='qwen3-asr',max_seconds=1))
        port=server._server.sockets[0].getsockname()[1]
        try:
            async with AsyncClient.from_uri(f'tcp://127.0.0.1:{port}') as connection:
                await connection.write_event(Describe().event())
                event=await asyncio.wait_for(connection.read_event(),2)
                info=Info.from_event(event)
                self.assertEqual(info.asr[0].models[0].name,'qwen3-asr')
                self.assertTrue(info.asr[0].requires_external_vad)
                await connection.write_event(Transcribe(language='zh').event())
                await connection.write_event(AudioStart(rate=16000,width=2,channels=1).event())
                await connection.write_event(AudioChunk(audio=b'\0\0'*1600,rate=16000,width=2,channels=1).event())
                await connection.write_event(AudioStop().event())
                event=await asyncio.wait_for(connection.read_event(),2)
                self.assertEqual(Transcript.from_event(event).text,'你好')
                self.assertEqual(client.calls[0]['language'],'zh')
                await connection.write_event(AudioStart(rate=16000,width=2,channels=1).event())
                await connection.write_event(AudioChunk(audio=b'\0\0'*16001,rate=16000,width=2,channels=1).event())
                self.assertTrue(Error.is_type((await asyncio.wait_for(connection.read_event(),2)).type))
                self.assertEqual(len(client.calls),1)
        finally:
            await server.stop()
            if server._server:server._server.close();await server._server.wait_closed()
