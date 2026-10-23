import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sonovect.assets import verify, resolve
from sonovect.setup import selection, main
from sonovect.api import create_app
from sonovect.config import Settings


class SetupTests(unittest.TestCase):
    def test_verified_sdk_cache_needs_no_network(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'models/iic/test';cache.mkdir(parents=True)
            (cache/'w').write_bytes(b'original')
            model={'hub':'modelscope','repo_id':'iic/test','revision':'v2.0.4',
                   'files':{'w':{'size':8,'algorithm':'sha256','digest':hashlib.sha256(b'original').hexdigest()}}}
            with patch('sonovect.assets.catalog',return_value={'fsmn':model}):
                self.assertEqual(resolve('fsmn',str(root),offline=True),str(cache))
                (cache/'w').write_bytes(b'modified')
                with self.assertRaisesRegex(RuntimeError,'digest_mismatch'):resolve('fsmn',str(root),offline=True)

    def test_selection_only_downloads_required_assets(self):
        plain = selection()
        self.assertNotIn('moss-4b', plain['models'])
        self.assertNotIn('fsmn', plain['models'])
        full = selection(sound='ast', voice='4b')
        self.assertIn('moss-4b', full['models'])
        self.assertIn('ast-events', full['models'])
        self.assertEqual(full['environment']['COMPOSE_PROFILES'], 'analysis,voice')
        self.assertNotIn('ast-events', selection(sound='none', voice='4b')['models'])
        with self.assertRaises(ValueError):selection(sound='4b')
        self.assertGreater(full['download_bytes'], plain['download_bytes'])
        self.assertTrue(selection(speech='0.6b')['experimental'])
        self.assertEqual(selection(voice='8b')['environment']['MOSS_GPU_BUDGET_MIB'],'19456')
        cpu = selection(route='cpu', sound='ast')
        self.assertIn('ast-events', cpu['models'])
        self.assertNotIn('moss-4b', cpu['models'])
        alternative = selection(route='cpu', native_revision='v2.0.9')
        self.assertIn('paraformer-v2.0.9', alternative['models'])
        self.assertEqual(alternative['environment']['SONOVECT_MODEL_REVISION'],'v2.0.9')
        self.assertTrue(alternative['experimental'])
        self.assertEqual(selection(route='cpu',vad='fsmn')['vad'],'fsmn')
        with self.assertRaises(ValueError):selection(route='cpu',vad='firered')

    def test_corrupt_or_missing_bytes_fail_without_overwriting(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);f=root/'w';f.write_bytes(b'original')
            m={'files':{'w':{'size':8,'algorithm':'sha256','digest':hashlib.sha256(b'original').hexdigest()}}}
            self.assertEqual(verify(root,m),str(root))
            f.write_bytes(b'modified')
            with self.assertRaisesRegex(RuntimeError,'digest_mismatch'):verify(root,m)
            f.unlink()
            with self.assertRaisesRegex(RuntimeError,'missing'):verify(root,m)

    def test_disabled_sound_is_discoverable_and_rejected_before_queue(self):
        with TemporaryDirectory() as tmp:
            with TestClient(create_app(Settings(data_dir=Path(tmp),token='setup-test-token',backend='speech',sound_enabled=False))) as c:
                c.headers['Authorization']='Bearer setup-test-token'
                self.assertFalse(c.get('/v1/capabilities').json()['sound_analysis'])
                self.assertEqual(c.post('/v1/jobs',files={'files':('a.wav',b'a')},data={'options':'{"analyze_sound":true}'}).status_code,422)

    def test_configuration_secret_is_private_and_never_overwritten(self):
        import io,stat
        from contextlib import redirect_stdout,redirect_stderr
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'.env';out=io.StringIO()
            with redirect_stdout(out):self.assertEqual(main(['--write',str(p)]),0)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
            secret=next(v.split('=',1)[1] for v in p.read_text().splitlines() if v.startswith('SONOVECT_TOKEN='))
            self.assertNotIn(secret,out.getvalue())
            with redirect_stderr(io.StringIO()):self.assertEqual(main(['--write',str(p)]),1)
