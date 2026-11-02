"""Readiness contracts across real HTTP, authentication, clients and deadlines."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import httpx

from sonovect import __version__
from sonovect.api import create_app
from sonovect.cli import main
from sonovect.client import Client
from sonovect.config import Settings
from sonovect.readiness import Readiness, SCOPE, fetch_health, provider_checks, report
from sonovect.store import Store


def discovery(gpu_error=None):
    return {'status': 'degraded' if gpu_error else 'ok', 'voice_analysis': False, 'voice_measurements': False,
            'upstreams': {
                'qwen3_asr': {'reachable': True, 'payload': {'status': 'degraded' if gpu_error else 'ok',
                    'gpu_access': {'available': not bool(gpu_error), 'error': gpu_error},
                    'manager': {'loaded': False, 'busy': True, 'last_load_error': None}}},
                'segmentation': {'reachable': True, 'payload': {'status': 'ok'}},
                'events': {'reachable': False, 'error': 'provider_timeout'}}}


class DiagnosticsTests(unittest.TestCase):
    def test_gpu_failure_authentication_and_secret_filtering(self):
        with TemporaryDirectory() as raw:
            s = Settings(data_dir=Path(raw), token='test-secret', backend='speech')
            Store(s).worker_seen('worker', 'speech', __version__, True)
            app = create_app(s)
            private = discovery('gpu_device_access_denied')
            private['secret'] = 'private-fixture-value'
            private['upstreams']['qwen3_asr']['payload']['manager']['path'] = '/private/runtime/model'
            with patch('sonovect.readiness.fetch_health', new=AsyncMock(return_value=(private, None))), TestClient(app) as api:
                self.assertEqual(api.get('/health').status_code, 200)
                self.assertEqual(api.get('/v1/diagnostics/readiness').status_code, 401)
                summary = api.get('/ready');self.assertEqual(summary.status_code, 503)
                self.assertEqual(summary.json()['code'], 'gpu_device_access_denied')
                self.assertEqual(summary.json()['available_workers'], 1)
                self.assertNotIn('checks', summary.json())
                detail = api.get('/v1/diagnostics/readiness', headers={'Authorization': 'Bearer test-secret'})
                self.assertEqual(detail.status_code, 503)
                self.assertEqual(detail.json()['errors'], [{'component': 'speech.asr', 'code': 'gpu_device_access_denied'}])
                self.assertEqual(detail.json()['warnings'][0]['code'], 'provider_timeout')
                self.assertNotIn('private-fixture-value', detail.text)
                self.assertNotIn('/private/runtime/model', detail.text)
                self.assertEqual(summary.json()['code'], detail.json()['code'])

    def test_optional_failure_idle_models_and_configuration_contract(self):
        s = Settings(token='test-secret', backend='speech')
        value = discovery()
        r = report(provider_checks(s, value), 1)
        self.assertEqual(r.status, 'ready')
        self.assertEqual(r.warnings[0].component, 'analysis.events')
        value['voice_analysis'] = True
        self.assertEqual(report(provider_checks(s, value)).code, 'provider_configuration_mismatch')
        self.assertEqual(report(provider_checks(s, {'status':'ok'})).status, 'ready')
        self.assertEqual(report(provider_checks(s, {'status':[]})).code, 'provider_invalid_response')
        self.assertEqual(report(provider_checks(s, {'status':'degraded'})).code, 'provider_degraded')

    def test_missing_database_is_not_created_by_diagnostic(self):
        with TemporaryDirectory() as raw:
            s = Settings(data_dir=Path(raw)/'absent', token='test-secret')
            value = asyncio.run(Readiness(s).get())
            self.assertEqual(value['code'], 'database_unavailable')
            self.assertIsNone(value['available_workers'])
            self.assertFalse(s.data_dir.exists())
            self.assertEqual(value['checks'][1]['status'], 'skipped')

    def test_old_server_fallback_and_invalid_error_responses(self):
        for status, body in [(200, {'status':'ready','scope':SCOPE,'available_workers':1}),
                             (503, {'status':'not_ready','scope':SCOPE})]:
            def handle(request):
                return httpx.Response(404 if request.url.path.startswith('/v1/') else status,
                                      json={} if request.url.path.startswith('/v1/') else body)
            with_client = Client(token='test-secret', transport=httpx.MockTransport(handle))
            try:
                value = with_client.readiness(details=True)
                self.assertFalse(value['details_supported'])
                self.assertEqual(value['status'], body['status'])
            finally:with_client.close()
        for status, body in [(401, {}), (503, {'message':'private-fixture-value'}), (503, {'status':'ready','scope':SCOPE}),
                (200, {'status':'ready','scope':SCOPE,'code':'gpu_device_access_denied','component':'speech.asr'})]:
            c = Client(token='test-secret', transport=httpx.MockTransport(lambda request:httpx.Response(status,json=body)))
            try:
                with self.assertRaisesRegex(RuntimeError, '^invalid_readiness_response$'):c.readiness()
                if status >= 400:
                    with self.assertRaises(RuntimeError):c.request('GET','/ready')
            finally:c.close()

    def test_cli_failure_is_structured_stdout_and_nonzero_exit(self):
        body = {'status':'not_ready','scope':SCOPE,'code':'gpu_device_access_denied','component':'speech.asr','available_workers':1}
        def client():return Client(token='test-secret', transport=httpx.MockTransport(lambda request:httpx.Response(503,json=body)))
        out, err = StringIO(), StringIO()
        with patch('httpx._client.logger'), patch('sonovect.cli.Client',side_effect=client), redirect_stdout(out), redirect_stderr(err):
            code = main(['ready'])
        self.assertEqual(code,1);self.assertEqual(err.getvalue(),'')
        self.assertEqual(json.loads(out.getvalue())['code'],'gpu_device_access_denied')

    def test_native_worker_presence_classification_and_no_writes(self):
        with TemporaryDirectory() as raw:
            s=Settings(data_dir=Path(raw),token='test-secret');store=Store(s)
            scenarios=[('speech',__version__,True,'worker_backend_mismatch'),
                       ('funasr','older',True,'worker_version_mismatch'),
                       ('funasr',__version__,False,'worker_unavailable'),
                       ('funasr',__version__,True,None)]
            for backend,version,available,expected in scenarios:
                with store.connect() as con:con.execute('DELETE FROM workers')
                store.worker_seen('worker',backend,version,available)
                before=store.database.read_bytes()
                self.assertEqual(Store.worker_snapshot(s,__version__)['code'],expected)
                self.assertEqual(store.database.read_bytes(),before)


class AsyncDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_timed_out_database_probe_is_not_duplicated_while_pending(self):
        release = threading.Event()
        def slow(settings, version):
            # Keep the probe pending until the assertions finish, including on
            # a busy host where three deadlines may exceed a short fixed sleep.
            release.wait(5)
            return {'available_workers':1,'code':None}
        service=Readiness(Settings(token='test-secret'),cache_seconds=0,deadline=.03)
        try:
            with patch('sonovect.readiness.Store.worker_snapshot',side_effect=slow) as probe:
                for _ in range(3):
                    self.assertEqual((await service.get())['code'],'probe_timeout')
                self.assertEqual(probe.call_count,1)
        finally:
            release.set()
            await service.close()

    async def test_concurrent_requests_share_collection_and_cache_expires(self):
        with TemporaryDirectory() as raw:
            s=Settings(data_dir=Path(raw),token='test-secret',backend='speech');Store(s).worker_seen('worker','speech',__version__,True)
            service=Readiness(s,cache_seconds=.05)
            async def fetch(url):
                await asyncio.sleep(.02)
                return discovery(),None
            with patch('sonovect.readiness.fetch_health',side_effect=fetch) as probe:
                results=await asyncio.gather(*(service.get() for _ in range(15)))
                self.assertEqual(probe.call_count,1)
                self.assertTrue(all(v['status']=='ready' for v in results))
                await service.get();self.assertEqual(probe.call_count,1)
                await asyncio.sleep(.06)
                await service.get();self.assertEqual(probe.call_count,2)
            await service.close()

    async def test_total_deadline_preserves_other_failures_and_cancels_probe(self):
        with TemporaryDirectory() as raw:
            s=Settings(data_dir=Path(raw),token='test-secret',backend='speech');Store(s)
            cancelled=asyncio.Event()
            async def hang(url):
                try:await asyncio.sleep(30)
                finally:cancelled.set()
            service=Readiness(s,deadline=.05)
            with patch('sonovect.readiness.fetch_health',side_effect=hang):
                started=time.monotonic();value=await service.get()
            self.assertLess(time.monotonic()-started,.5);self.assertTrue(cancelled.is_set())
            self.assertEqual([v['code'] for v in value['errors']],['worker_absent','probe_timeout'])
            await service.close()

    async def test_real_slow_http_and_response_limits(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.end_headers()
                try:
                    if self.path.startswith('/large'):
                        self.wfile.write(b'x'*70000);return
                    self.wfile.write(b'{');self.wfile.flush();time.sleep(.5);self.wfile.write(b'}')
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}'
            started=time.monotonic();_,code=await fetch_health(root,timeout=.08)
            self.assertEqual(code,'provider_timeout');self.assertLess(time.monotonic()-started,.4)
            _,code=await fetch_health(root+'/large',timeout=.3)
            self.assertEqual(code,'provider_invalid_response')
        finally:
            await asyncio.to_thread(server.shutdown);server.server_close();thread.join()


if __name__=='__main__':unittest.main()
