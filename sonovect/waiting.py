"""One bounded synchronous waiter for adapters over the durable file queue."""
import asyncio
import time
from fastapi.responses import JSONResponse, Response
from .store import TERMINAL


def job_headers(job_id):
    return {"X-Sonovect-Job-ID": job_id, "x-should-retry": "false"}


async def await_job(request, settings, store, job_id, operation="transcription"):
    deadline = time.monotonic() + settings.sync_timeout
    while True:
        job = await asyncio.to_thread(store.get, job_id)
        if job["state"] in TERMINAL:
            return job
        if time.monotonic() >= deadline:
            code = operation + "_wait_timeout"
            return JSONResponse({"error": {"message": code, "type": "server_error", "code": code, "param": None}},
                                status_code=408, headers=job_headers(job_id))
        if await request.is_disconnected():
            return Response(status_code=499, headers=job_headers(job_id))
        await asyncio.sleep(.05)
