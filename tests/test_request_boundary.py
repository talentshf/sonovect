"""Unauthorized uploads must never reach receive(), parsing, or temporary files."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from sonovect.api import create_app
from sonovect.config import Settings


class RequestBoundaryTests(unittest.TestCase):
    def request(self, app, headers, body=b'', chunked=False):
        messages, reads = [], []
        chunks = [body[:len(body)//2], body[len(body)//2:]] if chunked else [body]
        async def receive():
            reads.append(True)
            part = chunks.pop(0)
            return {'type': 'http.request', 'body': part, 'more_body': bool(chunks)}
        async def send(message):messages.append(message)
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST', 'path': '/v1/jobs',
                 'raw_path': b'/v1/jobs', 'query_string': b'', 'headers': headers,
                 'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1), 'root_path': ''}
        asyncio.run(app(scope, receive, send))
        return next(m['status'] for m in messages if m['type']=='http.response.start'), reads, messages

    def test_invalid_authentication_reads_zero_body_bytes_even_above_limit(self):
        with TemporaryDirectory() as tmp:
            app=create_app(Settings(data_dir=Path(tmp),token='test-boundary-token',max_upload_bytes=1))
            for credentials in [[], [(b'authorization',b'Basic x')], [(b'authorization',b'Bearer wrong')],
                                [(b'authorization',b'Bearer test-boundary-token')]*2]:
                for length in [[], [(b'content-length', b'999999999')]]:
                    status, reads, messages=self.request(app,credentials+length,b'x'*2**21)
                    self.assertEqual(status,401);self.assertEqual(reads,[])
                    self.assertIn((b'www-authenticate',b'Bearer'),messages[0]['headers'])
            self.assertFalse(list(Path(tmp).glob('upload-*')))

    def test_authenticated_chunked_and_content_length_limits_still_reject(self):
        with TemporaryDirectory() as tmp:
            app=create_app(Settings(data_dir=Path(tmp),token='test-boundary-token',max_upload_bytes=1))
            headers=[(b'authorization',b'Bearer test-boundary-token')]
            self.assertEqual(self.request(app,headers+[(b'content-length',b'999999999')])[0],413)
            self.assertEqual(self.request(app,headers+[(b'content-type',b'multipart/form-data; boundary=test-boundary')],
                b'--test-boundary\r\nContent-Disposition: form-data; name="files"; filename="a.wav"\r\n\r\n'+b'x'*400000+b'\r\n--test-boundary--\r\n',True)[0],413)
