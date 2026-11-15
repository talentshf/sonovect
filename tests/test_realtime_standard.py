"""Native OpenAI WebSocket client, committed-turn lifecycle and model ownership."""
import base64
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
import unittest
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import OpenAI
from starlette.websockets import WebSocketDisconnect
import uvicorn

from sonovect.config import Settings
from sonovect.realtime_standard import install, session_options
from sonovect.recognition import Recognition


class Engine:
    def __init__(self):
        self.calls = []

    def process_stream(self, path, key, options, progress):
        with wave.open(str(path)) as audio:
            assert audio.getframerate() == 24000 and audio.getnchannels() == 1
        self.calls.append(options)
        progress({"text": "你"})
        progress({"text": "你好"})
        return Recognition({"key": key, "text": "你好"}, {"key": key, "status": "not_requested"}, {})


class StandardRealtimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), token="native-realtime-test", backend="speech",
                                 realtime_enabled=True, realtime_max_sessions=1)
        self.engine = Engine()
        self.app = FastAPI()
        install(self.app, self.settings, self.engine)
        self.headers = {"Authorization": "Bearer " + self.settings.token}

    def tearDown(self):
        self.tmp.cleanup()

    def test_neural_server_vad_commits_a_real_turn_once_and_ignores_later_silence(self):
        from dataclasses import replace
        async def probabilities(pcm,rate):
            size=rate//100*2
            return [.95 if any(pcm[i:i+size]) else .01 for i in range(0,len(pcm),size)]
        settings=replace(self.settings,realtime_vad_enabled=True)
        app=FastAPI();install(app,settings,self.engine,vad=probabilities)
        with TestClient(app) as client,client.websocket_connect('/v1/realtime?intent=transcription',headers=self.headers) as ws:
            ws.receive_json()
            ws.send_json({'type':'session.update','session':{'type':'transcription','audio':{'input':{
                'turn_detection':{'type':'server_vad','prefix_padding_ms':100,'silence_duration_ms':300}}}}})
            self.assertEqual(ws.receive_json()['session']['audio']['input']['turn_detection']['type'],'server_vad')
            pcm=b'\0\0'*7200+b'\1\0'*12000+b'\0\0'*16800
            ws.send_json({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm).decode()})
            events=[]
            while True:
                value=ws.receive_json();events.append(value)
                if value['type'].endswith('.completed'):break
            self.assertEqual(events[0]['type'],'input_audio_buffer.speech_started')
            self.assertEqual(events[1]['type'],'input_audio_buffer.speech_stopped')
            self.assertEqual(events[0]['item_id'],events[2]['item_id'])
            self.assertEqual(events[-1]['transcript'],'你好');self.assertEqual(len(self.engine.calls),1)
            ws.send_json({'type':'input_audio_buffer.append','audio':base64.b64encode(b'\0\0'*72000).decode()})
            ws.send_json({'type':'input_audio_buffer.clear'})
            self.assertEqual(ws.receive_json()['type'],'input_audio_buffer.cleared')
            self.assertEqual(len(self.engine.calls),1)

    def test_cli_stream_uses_standard_events_over_real_websocket(self):
        import io,json
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from sonovect.cli import main
        sock=socket.socket();sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(self.app,log_level="critical"))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        try:
            deadline=time.monotonic()+3
            while not server.started:
                self.assertLess(time.monotonic(),deadline);time.sleep(.01)
            path=Path(self.tmp.name)/"live.wav"
            with wave.open(str(path),"wb") as out:
                out.setparams((1,2,24000,0,"NONE","not compressed"));out.writeframes(b"\0\0"*24000)
            result=io.StringIO()
            with patch.dict("os.environ",{"SONOVECT_URL":f"http://127.0.0.1:{port}","SONOVECT_TOKEN":self.settings.token,"SONOVECT_TOKEN_FILE":""}),redirect_stdout(result):
                self.assertEqual(main(["stream",str(path),"--language","zh"]),0)
            values=[json.loads(line) for line in result.getvalue().splitlines()]
            self.assertEqual(values[0]["type"],"session.created")
            self.assertEqual(values[-1]["transcript"],"你好")
            self.assertEqual(self.engine.calls[0]["language"],"zh")
        finally:
            server.should_exit=True;thread.join(3);sock.close()

    def test_unmodified_openai_sdk_commits_multiple_turns_without_loading_a_second_model(self):
        sock = socket.socket(); sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.app, log_level="critical"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        sdk = OpenAI(api_key=self.settings.token, websocket_base_url=f"ws://127.0.0.1:{port}/v1")
        try:
            deadline = time.monotonic() + 3
            while not server.started:
                self.assertLess(time.monotonic(), deadline); time.sleep(.01)
            with sdk.realtime.connect(extra_query={"intent": "transcription"}, max_retries=0) as connection:
                event = connection.recv()
                self.assertEqual(event.type, "session.created")
                self.assertEqual(event.session.type, "transcription")
                connection.session.update(session={"type": "transcription", "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "qwen3-asr", "language": "zh"}, "turn_detection": None}}})
                self.assertEqual(connection.recv().type, "session.updated")
                prior = None
                for _ in range(2):
                    connection.input_audio_buffer.append(audio=base64.b64encode(b"\0\0"*2400).decode())
                    self.assertEqual(len(self.engine.calls), 0 if prior is None else 1)
                    connection.input_audio_buffer.commit()
                    committed = connection.recv()
                    self.assertEqual(committed.type, "input_audio_buffer.committed")
                    self.assertEqual(committed.previous_item_id, prior)
                    created = connection.recv()
                    self.assertEqual(created.type, "conversation.item.created")
                    self.assertEqual(created.item.id, committed.item_id)
                    deltas = []
                    while True:
                        event = connection.recv()
                        self.assertEqual(event.item_id, committed.item_id)
                        if event.type == "conversation.item.input_audio_transcription.completed":
                            self.assertEqual(event.transcript, "".join(deltas))
                            self.assertEqual(event.usage.type, "duration")
                            self.assertEqual(event.usage.seconds, .1)
                            break
                        self.assertEqual(event.type, "conversation.item.input_audio_transcription.delta")
                        deltas.append(event.delta)
                    prior = committed.item_id
            self.assertEqual(len(self.engine.calls), 2)
            self.assertTrue(all(not x["speakers"] and x["timestamps"] == "none" for x in self.engine.calls))
            self.assertFalse(list(Path(self.tmp.name).glob("realtime-*")))
        finally:
            sdk.close(); server.should_exit = True; thread.join(3); sock.close()
        self.assertFalse(thread.is_alive())

    def test_authentication_bounds_and_invalid_configuration_do_not_run_recognition(self):
        with TestClient(self.app) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/v1/realtime?intent=transcription"):
                    pass
            with client.websocket_connect("/v1/realtime?intent=transcription", headers=self.headers) as first:
                self.assertEqual(first.receive_json()["type"], "session.created")
                with client.websocket_connect("/v1/realtime?intent=transcription", headers=self.headers) as other:
                    self.assertEqual(other.receive_json()["error"]["code"], "realtime_busy")
                first.send_text("not-json")
                self.assertEqual(first.receive_json()["type"], "error")
                first.send_json({"type": "input_audio_buffer.append", "audio": base64.b64encode(b"x").decode()})
                self.assertEqual(first.receive_json()["error"]["code"], "invalid_pcm_frame")
                first.send_json({"type": "session.update", "session": {"audio": {"input": {"turn_detection": {"type": "server_vad"}}}}})
                self.assertEqual(first.receive_json()["error"]["code"], "server_vad_not_configured")
                first.send_json({"type": "input_audio_buffer.clear"})
                self.assertEqual(first.receive_json()["type"], "input_audio_buffer.cleared")
        self.assertEqual(self.engine.calls, [])

    def test_explicit_language_options_and_unsupported_logprobs(self):
        selected = session_options({"audio": {"input": {"transcription": {"model": "qwen3-asr", "languages": ["en", "zh"], "keywords": ["Sonovect"]}}}}, self.settings)
        self.assertIsNone(selected.language)
        self.assertIn("en, zh", selected.context)
        self.assertEqual(selected.hotwords, ["Sonovect"])
        with self.assertRaises(ValueError):
            session_options({"include": ["item.input_audio_transcription.logprobs"]}, self.settings)
