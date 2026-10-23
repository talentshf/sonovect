"""Real SQLite contention, retention revalidation and worker survival."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sonovect.config import Settings
from sonovect.store import Conflict, Store, StoreBusy
from sonovect.worker import Worker


class SQLiteContentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.settings=Settings(data_dir=self.root/'data',token='sqlite-test',poll_seconds=.01)
        self.store=Store(self.settings);self.original_connect=self.store.connect
        @contextmanager
        def quick():
            with self.original_connect() as con:
                con.execute('PRAGMA busy_timeout=10')
                yield con
        self.store.connect=quick

    def queued(self):
        p=self.root/'incoming';p.write_bytes(b'public-test')
        return self.store.admit([dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size)],{})[0]

    def partial(self):
        job=self.queued();row=self.store.claim('owner')
        self.store.finish(job,'owner','partial',row['sources'],[dict(key='a',text='retained')],[])
        return job

    def test_idle_claim_and_prune_read_while_another_writer_holds_lock(self):
        with self.original_connect() as holder:
            holder.execute('BEGIN IMMEDIATE')
            self.assertIsNone(self.store.claim('idle'))
            self.assertEqual(self.store.prune(),0)

    def test_input_cleanup_runs_once_and_legacy_numeric_retry_rejects_it(self):
        job=self.partial()
        with self.original_connect() as con:con.execute('UPDATE jobs SET input_expires=? WHERE id=?',(time.time()-1,job))
        begins=[]
        @contextmanager
        def traced():
            with self.original_connect() as con:
                con.set_trace_callback(lambda sql: begins.append(sql) if sql.startswith('BEGIN') else None)
                yield con
        self.store.connect=traced
        self.assertEqual(self.store.prune(),0)
        row=self.store.get(job);self.assertEqual(row['input_expires'],0)
        self.assertLessEqual(row['input_expires'],time.time())
        self.assertEqual(row['result'][0]['text'],'retained')
        self.assertFalse((self.store.root/'inputs'/job).exists())
        self.assertEqual(self.store.prune(),0);self.assertEqual(len(begins),1)
        with self.assertRaisesRegex(Conflict,'input_expired'):self.store.retry(job)

    def test_failed_removal_keeps_cleanup_due_and_retry_denied(self):
        job=self.partial()
        with self.original_connect() as con:con.execute('UPDATE jobs SET input_expires=? WHERE id=?',(time.time()-1,job))
        with patch('sonovect.store.shutil.rmtree') as remove:
            self.store.prune();self.store.prune();self.assertEqual(remove.call_count,2)
        self.assertGreater(self.store.get(job)['input_expires'],0)
        with self.assertRaisesRegex(Conflict,'input_expired'):self.store.retry(job)

    def test_failed_removal_at_result_expiry_retries_before_input_deadline(self):
        job=self.partial()
        with self.original_connect() as con:con.execute('UPDATE jobs SET expires=? WHERE id=?',(time.time()-1,job))
        self.assertGreater(self.store.get(job)['input_expires'],time.time())
        with patch('sonovect.store.shutil.rmtree') as remove:
            self.assertEqual(self.store.prune(),1)
            self.assertEqual(self.store.get(job)['state'],'expired')
            self.assertEqual(self.store.prune(),0)
            self.assertEqual(remove.call_count,2)
        self.store.prune()
        self.assertEqual(self.store.get(job)['input_expires'],0)
        self.assertFalse((self.store.root/'inputs'/job).exists())

    def interleave(self, callback):
        """Run another real connection after a preflight read, before BEGIN."""
        original=self.original_connect;fired=[]
        class Cursor:
            def __init__(self,cursor):self.cursor=cursor
            def fetchone(self):
                row=self.cursor.fetchone();self.cursor.close()
                if not fired:fired.append(True);callback()
                return row
            def close(self):self.cursor.close()
        class Connection:
            def __init__(self,con):self.con=con
            def execute(self,sql,*args):
                cursor=self.con.execute(sql,*args)
                return Cursor(cursor) if sql.startswith('SELECT 1 FROM jobs') else cursor
        @contextmanager
        def intercepted():
            with original() as con:yield Connection(con)
        self.store.connect=intercepted

    def test_retention_rechecks_a_retry_that_won_the_writer_race(self):
        job=self.partial();other=Store(self.settings)
        with self.original_connect() as con:con.execute('UPDATE jobs SET expires=? WHERE id=?',(time.time()-1,job))
        self.interleave(lambda: other.retry(job))
        self.assertEqual(self.store.prune(),0)
        self.assertEqual(other.get(job)['state'],'queued')
        self.assertTrue((self.store.root/'inputs'/job/'0000.audio').is_file())

    def test_claim_rechecks_when_another_worker_won_the_lease(self):
        job=self.queued();other=Store(self.settings)
        self.interleave(lambda: other.claim('other'))
        self.assertIsNone(self.store.claim('loser'))
        self.assertEqual(other.get(job)['lease_owner'],'other')

    def worker(self):
        worker=Worker(self.settings,backend=SimpleNamespace(available=lambda: True))
        worker.store=self.store;worker.announce=Mock();worker.store.worker_departed=Mock()
        return worker

    def test_worker_survives_actual_busy_writer_then_claims_same_job(self):
        job=self.queued();worker=self.worker();stopping=threading.Event();blocked=threading.Event();errors=[];claimed=[]
        def once():
            try:row=self.store.claim(worker.owner)
            except StoreBusy:blocked.set();raise
            if row:claimed.append(row['id']);stopping.set()
            return bool(row)
        worker.run_once=once
        def serve():
            try:worker.serve(stopping)
            except BaseException as error:errors.append(error);blocked.set()
        health=self.root/'health.json';thread=threading.Thread(target=serve)
        with patch.dict('os.environ',{'SONOVECT_WORKER_HEALTH_FILE':str(health)}), self.assertLogs('sonovect.worker',level='WARNING') as logs:
            try:
                with self.original_connect() as holder:
                    holder.execute('BEGIN IMMEDIATE');thread.start()
                    self.assertTrue(blocked.wait(3))
                    self.assertTrue(thread.is_alive())
                    self.assertEqual(self.store.get(job)['state'],'queued')
                thread.join(5)
            finally:stopping.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(claimed,[job])
        self.assertIn('Queue database busy','\n'.join(logs.output));self.assertFalse(health.exists())

    def test_permanent_storage_error_still_stops_worker(self):
        worker=self.worker();stopping=threading.Event();error=sqlite3.OperationalError('disk I/O error')
        worker.run_once=Mock(side_effect=error)
        with patch.dict('os.environ',{'SONOVECT_WORKER_HEALTH_FILE':str(self.root/'health.json')}):
            with self.assertRaisesRegex(sqlite3.OperationalError,'disk I/O'):worker.serve(stopping)

    def test_busy_presence_and_departure_do_not_prevent_orderly_recovery(self):
        worker=self.worker();stopping=threading.Event();worker.announce.side_effect=StoreBusy('database_busy')
        worker.store.worker_departed.side_effect=StoreBusy('database_busy')
        worker.run_once=lambda: stopping.set()
        health=self.root/'health.json'
        with patch.dict('os.environ',{'SONOVECT_WORKER_HEALTH_FILE':str(health)}), self.assertLogs('sonovect.worker',level='WARNING'):
            worker.serve(stopping)
        self.assertFalse(health.exists())

if __name__=='__main__':unittest.main()
