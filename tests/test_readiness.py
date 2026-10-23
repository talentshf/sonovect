from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time
import unittest
from fastapi.testclient import TestClient
from sonovect import __version__
from sonovect.api import create_app
from sonovect.auth import token_from_env
from sonovect.config import Settings
from sonovect.store import Store

class ReadinessTests(unittest.TestCase):
    def test_no_absent_stale_wrong_backend_or_wrong_version_worker(self):
        with TemporaryDirectory() as raw:
            settings = Settings(data_dir=Path(raw), token="test-secret", backend="funasr")
            store = Store(settings)
            with TestClient(create_app(settings)) as api:
                self.assertEqual(api.get("/ready").status_code,503)
                store.worker_seen("one","speech",__version__,True)
                store.worker_seen("two","funasr","older",True)
                store.worker_seen("three","funasr",__version__,False)
                self.assertEqual(api.get("/ready").status_code,503)
                store.worker_seen("actual","funasr",__version__,True)
                self.assertEqual(api.get("/ready").status_code,200)
                self.assertEqual(store.available_workers(__version__,"different-process"),0)
                with store.connect() as con:
                    con.execute("UPDATE workers SET seen=?",(time.time()-60,))
                self.assertEqual(api.get("/ready").status_code,503)
    def test_explicit_token_file_and_conflict(self):
        with TemporaryDirectory() as raw:
            path=Path(raw)/"token";path.write_text("test-secret\n")
            with patch.dict("os.environ",{"SONOVECT_TOKEN_FILE":str(path)},clear=True):
                self.assertEqual(token_from_env(),"test-secret")
            with patch.dict("os.environ",{"SONOVECT_TOKEN_FILE":str(path),"SONOVECT_TOKEN":"second"},clear=True):
                with self.assertRaises(ValueError):token_from_env()
