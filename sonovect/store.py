"""Durable local queue with atomic claims, leases and bounded retention."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid

TERMINAL = {"succeeded", "partial", "failed", "cancelled", "expired"}


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


class Conflict(ValueError):
    pass


class StoreBusy(RuntimeError):
    """A transient SQLite writer conflict; the transaction has been rolled back."""


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / "inputs").mkdir(exist_ok=True, mode=0o700)
        self.database = self.root / "jobs-v1.sqlite3"
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, finished REAL, expires REAL, input_expires REAL,
                options TEXT NOT NULL, sources TEXT NOT NULL, result TEXT, analysis TEXT,
                error TEXT, idempotency_key TEXT UNIQUE, fingerprint TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1, lease_owner TEXT, lease_until REAL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY, backend TEXT NOT NULL, version TEXT NOT NULL,
                available INTEGER NOT NULL, seen REAL NOT NULL
            )""")
        os.chmod(self.database, 0o600)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.database, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            # The queue never consumes caller SQL, attached databases or
            # extensions. Enforce that boundary on every connection, including
            # reopened workers; parameter binding alone does not harden a
            # corrupted on-disk schema. This does not repair SQLite itself.
            con.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
            con.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
            con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION, False)
            con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            con.execute("PRAGMA cell_size_check=ON")
            with con:
                yield con
        except sqlite3.OperationalError as error:
            code = getattr(error, "sqlite_errorcode", None)
            if isinstance(code, int) and code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise StoreBusy("database_busy") from None
            raise
        finally:
            con.close()

    def worker_seen(self, owner, backend, version, available):
        now = time.time()
        with self.connect() as con:
            con.execute("""INSERT INTO workers(id,backend,version,available,seen)
                VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                backend=excluded.backend,version=excluded.version,
                available=excluded.available,seen=excluded.seen""",
                (owner, backend, version, int(available), now))
            con.execute("DELETE FROM workers WHERE seen<?", (now - 86400,))

    def worker_departed(self, owner):
        with self.connect() as con:
            con.execute("DELETE FROM workers WHERE id=?", (owner,))

    def available_workers(self, version, owner=None):
        with self.connect() as con:
            return con.execute("""SELECT count(*) FROM workers
                WHERE backend=? AND version=? AND available=1 AND seen>?
                AND (? IS NULL OR id=?)""",
                (self.settings.backend, version, time.time() - self.settings.worker_stale_seconds, owner, owner)).fetchone()[0]

    def get(self, job_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        value = dict(row)
        for name in ("options", "sources", "result", "analysis"):
            value[name] = json.loads(value[name]) if value[name] is not None else None
        return value

    def public(self, job_id):
        row = self.get(job_id)
        return {"id": row["id"], "status": row["state"], "attempt": row["attempt"],
                "created_at": iso(row["created"]), "updated_at": iso(row["updated"]),
                "finished_at": iso(row["finished"]), "expires_at": iso(row["expires"]),
                "options": row["options"], "error": row["error"],
                "sources": [{k: v for k, v in source.items() if k != "path"} for source in row["sources"]]}

    def admit(self, sources, options, key=None):
        fingerprint = hashlib.sha256(encoded({"options": options, "inputs": [s["sha256"] for s in sources]})).hexdigest()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if key:
                old = con.execute("SELECT id,fingerprint FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise Conflict("idempotency_key_reused_with_different_input")
                    return old["id"], False
            job_id, now = uuid.uuid4().hex, time.time()
            folder = self.root / "inputs" / job_id
            folder.mkdir(mode=0o700)
            staged = []
            try:
                for i, source in enumerate(sources):
                    target = folder / f"{i:04}.audio"
                    shutil.move(source["path"], target)
                    os.chmod(target, 0o600)
                    staged.append({"key": f"audio_{i:04}", "path": str(target), "sha256": source["sha256"],
                                   "size": source["size"], "status": "queued"})
                con.execute("""INSERT INTO jobs
                    (id,state,created,updated,options,sources,idempotency_key,fingerprint)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (job_id, "queued", now, now, json.dumps(options), json.dumps(staged), key, fingerprint))
            except BaseException:
                shutil.rmtree(folder)
                raise
        return job_id, True

    def claim(self, owner):
        now = time.time()
        with self.connect() as con:
            # Idle polling needs no writer. Recheck candidates after taking
            # the write lock: another worker can claim/cancel in between.
            with closing(con.execute("""SELECT 1 FROM jobs WHERE state='queued' OR
                    (state IN ('running','cancelled') AND lease_until<?) LIMIT 1""", (now,))) as probe:
                pending = probe.fetchone()
            if pending is None:
                return None
            con.execute("BEGIN IMMEDIATE")
            # A stale cancelled attempt is not reprocessed.
            con.execute("UPDATE jobs SET lease_owner=NULL,lease_until=NULL WHERE state='cancelled' AND lease_until<?", (now,))
            row = con.execute("""SELECT id,state,updated FROM jobs WHERE state='queued' OR
                (state='running' AND lease_until<?) ORDER BY created LIMIT 1""", (now,)).fetchone()
            if not row:
                return None
            con.execute("UPDATE jobs SET state='running',updated=?,lease_owner=?,lease_until=? WHERE id=?",
                        (now, owner, now + self.settings.lease_seconds, row["id"]))
        job = self.get(row["id"])
        # Private telemetry, never persisted in results or public job schemas.
        # A reclaimed running lease has no comparable queue entry time.
        job["_queue_seconds"] = max(0, now - row["updated"]) if row["state"] == "queued" else None
        return job

    def heartbeat(self, job_id, owner):
        with self.connect() as con:
            return con.execute("""UPDATE jobs SET lease_until=? WHERE id=? AND lease_owner=?
                AND state IN ('running','cancelled')""", (time.time() + self.settings.lease_seconds, job_id, owner)).rowcount == 1

    def finish(self, job_id, owner, state, sources, result, analysis, error=None):
        now = time.time()
        with self.connect() as con:
            changed = con.execute("""UPDATE jobs SET state=?,sources=?,result=?,analysis=?,error=?,
                updated=?,finished=?,expires=?,input_expires=?,lease_owner=NULL,lease_until=NULL
                WHERE id=? AND state='running' AND lease_owner=?""",
                (state, json.dumps(sources), json.dumps(result, ensure_ascii=False), json.dumps(analysis, ensure_ascii=False),
                 error, now, now, now + self.settings.result_ttl_hours * 3600,
                 now + self.settings.input_ttl_hours * 3600, job_id, owner)).rowcount
            if not changed:
                con.execute("UPDATE jobs SET lease_owner=NULL,lease_until=NULL WHERE id=? AND state='cancelled' AND lease_owner=?", (job_id, owner))
        return bool(changed)

    def cancel(self, job_id):
        now = time.time()
        with self.connect() as con:
            con.execute("""UPDATE jobs SET state='cancelled',updated=?,finished=?,expires=?,input_expires=?
                WHERE id=? AND state IN ('queued','running')""",
                (now, now, now + self.settings.result_ttl_hours * 3600, now + self.settings.input_ttl_hours * 3600, job_id))
        return self.public(job_id)

    def retry(self, job_id):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["state"] not in {"partial", "failed", "cancelled"} or row["lease_owner"]:
                raise Conflict("job_not_retryable")
            sources = json.loads(row["sources"])
            if row["input_expires"] is None or row["input_expires"] <= time.time() or any(not Path(s["path"]).is_file() for s in sources):
                raise Conflict("input_expired_submit_new_job")
            for source in sources:
                source["status"] = "queued"
                source.pop("error", None)
                source.pop("media", None)
            con.execute("""UPDATE jobs SET state='queued',updated=?,finished=NULL,expires=NULL,
                input_expires=NULL,result=NULL,analysis=NULL,error=NULL,sources=?,attempt=attempt+1 WHERE id=?""",
                (time.time(), json.dumps(sources), job_id))
        return self.public(job_id)

    def prune(self):
        now, count = time.time(), 0
        due = """finished IS NOT NULL AND (lease_until IS NULL OR lease_until<?)
            AND ((input_expires>0 AND input_expires<=?) OR
                (expires<=? AND (state<>'expired' OR input_expires>0)))"""
        with self.connect() as con:
            with closing(con.execute("SELECT 1 FROM jobs WHERE " + due + " LIMIT 1", (now, now, now))) as probe:
                pending = probe.fetchone()
            if pending is None:
                return 0
            con.execute("BEGIN IMMEDIATE")
            # Status polling must not deserialize every retained transcript.
            # Keep the transaction: expiry cleanup and retry must not race.
            rows = con.execute("SELECT id,state,expires,input_expires FROM jobs WHERE " + due, (now, now, now)).fetchall()
            for row in rows:
                if (row["input_expires"] and row["input_expires"] <= now) or (row["expires"] and row["expires"] <= now):
                    folder = self.root / "inputs" / row["id"]
                    shutil.rmtree(folder, ignore_errors=True)
                    # Zero records confirmed input cleanup while preserving
                    # legacy numeric expiry checks on application rollback.
                    # Keep a due timestamp when removal failed, so it retries.
                    if not folder.exists():
                        con.execute("UPDATE jobs SET input_expires=0 WHERE id=?", (row["id"],))
                if row["expires"] and row["expires"] <= now and row["state"] != "expired":
                    con.execute("UPDATE jobs SET state='expired',result=NULL,analysis=NULL,options='{}',sources='[]',error=NULL,updated=? WHERE id=?", (now, row["id"]))
                    count += 1
        return count
