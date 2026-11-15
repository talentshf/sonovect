"""A local language request must not wait behind our own retained ASR model."""
import ast
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from fastapi import HTTPException


class TranslationCoordinationTests(unittest.TestCase):
    def run_request(self, confirmed=True):
        source = Path(__file__).parents[1] / "api/app.py"
        node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "local_translation")
        node.decorator_list = []
        events = []
        async def control(*args):
            events.append("release_asr")
            return {"status": "unloaded", "manager": {"resident": not confirmed, "busy": False}}
        async def sound(): events.append("release_sound")
        async def body(): return json.dumps({"model":"text-model","messages":[{"role":"user","content":"Translate quoted words"}],"stream":False}).encode()
        async def upstream(request):
            events.append("translate")
            self.assertEqual(request.url, "http://language/v1/chat/completions")
            return httpx.Response(200,json={"choices":[{"message":{"content":"Hello"}}]})
        real_client = httpx.AsyncClient
        ns = {"Request": object, "os": os, "json": json, "HTTPException": HTTPException,
              "GPU_PIPELINE_LOCK": asyncio.Lock(), "QWEN_URL":"asr", "QWEN_TIMEOUT":3,
              "_post_control":control,"_release_sound_before_speech":sound,"httpx":httpx}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),"exec"),ns)
        with patch.dict(os.environ,{"TRANSLATION_BACKEND_URL":"http://language/v1","SONOVECT_TRANSLATION_MODEL":"text-model","TRANSLATION_BACKEND_TOKEN_FILE":""}), patch.object(httpx,"AsyncClient",side_effect=lambda **kw: real_client(transport=httpx.MockTransport(upstream),**kw)):
            try: value=asyncio.run(ns["local_translation"](SimpleNamespace(body=body)))
            except HTTPException as error: value=error.status_code
        return value,events

    def test_confirmed_release_precedes_language_request(self):
        value,events=self.run_request()
        self.assertEqual(events,["release_asr","release_sound","translate"])
        self.assertEqual(value["choices"][0]["message"]["content"],"Hello")

    def test_failed_release_never_starts_language_model(self):
        value,events=self.run_request(False)
        self.assertEqual(value,503)
        self.assertEqual(events,["release_asr"])
