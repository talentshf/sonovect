from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from sonovect.config import Settings
from sonovect.store import Store


class StoreSecurityTests(unittest.TestCase):
    def test_each_reopened_connection_enforces_database_boundary(self):
        with TemporaryDirectory() as directory:
            store = Store(Settings(data_dir=Path(directory), token="test-only"))
            for _ in range(2):
                with store.connect() as con:
                    self.assertTrue(con.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE))
                    self.assertFalse(con.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA))
                    self.assertFalse(con.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION))
                    self.assertEqual(con.execute("PRAGMA cell_size_check").fetchone()[0], 1)
                    con.execute("PRAGMA writable_schema=ON")
                    self.assertEqual(con.execute("PRAGMA writable_schema").fetchone()[0], 0)
                    with self.assertRaises(sqlite3.OperationalError):
                        con.execute("ATTACH DATABASE ':memory:' AS injected")
                    with self.assertRaises(sqlite3.OperationalError):
                        con.execute("SELECT load_extension('not-an-extension')")
                    self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_untrusted_schema_cannot_invoke_application_function(self):
        with TemporaryDirectory() as directory:
            store = Store(Settings(data_dir=Path(directory), token="test-only"))
            with store.connect() as con:
                called = []
                con.create_function("private_function", 0, lambda: called.append(True) or "secret")
                con.execute("CREATE VIEW untrusted AS SELECT private_function()")
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute("SELECT * FROM untrusted").fetchall()
                self.assertEqual(called, [])
