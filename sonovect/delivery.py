"""Durable task events and signed completion delivery; never rerun inference."""
import asyncio
import hashlib
import hmac
import http.client
import json
import socket
import ssl
import time

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from .remote_input import input_url
from .media import MediaError
from .store import TERMINAL, encoded


def callback_url(value, settings):
    if value is None:
        return None
    try:
        p = input_url(value, settings.callback_hosts)
        if p.query:
            raise ValueError()
    except (ValueError, MediaError):
        raise HTTPException(422, "callback_url_not_allowed") from None
    return value


def deliver_one(store, sender=None):
    """A bounded, separately scheduled outbox attempt with an expiring claim."""
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("""SELECT c.*,e.attempt,e.created,e.kind,e.payload FROM job_callbacks c
            JOIN job_events e ON e.sequence=c.sequence WHERE c.state='pending' AND c.next_delivery<=?
            ORDER BY c.next_delivery LIMIT 1""", (time.time(),)).fetchone()
        if row is None:
            return False
        con.execute("UPDATE job_callbacks SET next_delivery=? WHERE job_id=?", (time.time() + 60, row["job_id"]))
    event = {"id": row["sequence"], "type": row["kind"], "job_id": row["job_id"],
             "attempt": row["attempt"], "data": json.loads(row["payload"])}
    timestamp = str(int(time.time()))
    body = encoded(event)
    signature = hmac.new(store.settings.token.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "Sonovect-Event-ID": str(row["sequence"]),
               "Sonovect-Timestamp": timestamp, "Sonovect-Signature": "v1=" + signature}
    status = None
    try:
        status = (sender or send_callback)(row["url"], body, headers, store.settings)
    except Exception:
        pass  # Neither response bodies nor destination credentials enter the log.
    attempts = row["attempts"] + 1
    state = "delivered" if status is not None and 200 <= status < 300 else "failed" if attempts >= 8 else "pending"
    with store.connect() as con:
        # A retried task can already have queued a newer terminal event.
        con.execute("""UPDATE job_callbacks SET state=?,attempts=?,last_status=?,next_delivery=?
            WHERE job_id=? AND sequence=?""", (state, attempts, status, time.time() + min(3600, 5 * 2**attempts),
                                               row["job_id"], row["sequence"]))
    return True


def send_callback(url, body, headers, settings):
    p = input_url(url, settings.callback_hosts)
    # Explicit operator allowlist, no redirects, and one pinned address per attempt.
    addresses = sorted({x[4][0] for x in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)})
    if not addresses:
        raise ValueError("callback_resolution_failed")
    connection = http.client.HTTPSConnection(p.hostname, timeout=10, context=ssl.create_default_context())
    connection._create_connection = lambda ignored, timeout, source_address=None: socket.create_connection(
        (addresses[0], 443), timeout=timeout, source_address=source_address)
    try:
        connection.request("POST", p.path or "/", body=body, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


def install(app, settings, store, authenticate):
    @app.get("/v1/jobs/{job_id}/events", dependencies=[Depends(authenticate)])
    async def events(job_id: str, request: Request, after: int = 0,
                     last_event_id: str | None = Header(default=None)):
        try:
            cursor = int(last_event_id) if last_event_id is not None else after
            if cursor < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "invalid_event_cursor") from None
        store.get(job_id)

        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                rows = await asyncio.to_thread(store.events, job_id, cursor)
                for event in rows:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                job = await asyncio.to_thread(store.get, job_id)
                if job["state"] in TERMINAL and len(rows) < 500:
                    return
                if time.monotonic() - heartbeat > 15:
                    heartbeat = time.monotonic()
                    yield ": heartbeat\n\n"
                await asyncio.sleep(.1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/v1/jobs/{job_id}/attempts", dependencies=[Depends(authenticate)])
    def attempts(job_id: str):
        values = store.attempts(job_id)
        for value in values:
            value["sources"] = [{k: v for k, v in source.items() if k in {"key", "sha256", "size", "status", "error", "media"}}
                                for source in value["sources"]]
        return {"job_id": job_id, "attempts": values}

    @app.get("/v1/jobs/{job_id}/notification", dependencies=[Depends(authenticate)])
    def notification(job_id: str):
        store.get(job_id)
        with store.connect() as con:
            row = con.execute("SELECT state,attempts,last_status,sequence FROM job_callbacks WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else {"state": "not_requested"}

    @app.post("/v1/jobs/{job_id}/notification/retry", dependencies=[Depends(authenticate)])
    def retry_notification(job_id: str):
        store.get(job_id)
        with store.connect() as con:
            if not con.execute("UPDATE job_callbacks SET state='pending',attempts=0,next_delivery=0 WHERE job_id=? AND sequence IS NOT NULL", (job_id,)).rowcount:
                raise HTTPException(409, "notification_unavailable")
        return notification(job_id)
