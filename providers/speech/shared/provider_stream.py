"""Internal NDJSON bridge. A disconnected consumer cannot release busy GPU work."""
import asyncio
import json
from fastapi.responses import StreamingResponse


def response(work):
    async def stream():
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        def emit(value):
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", "data": value})
        async def run():
            try:
                value = await work(emit)
                await queue.put({"type": "result", "data": value})
            except Exception:
                await queue.put({"type": "error", "code": "processing_failed"})
            finally:
                await queue.put(None)
        task = asyncio.create_task(run())
        try:
            while True:
                value = await queue.get()
                if value is None:
                    break
                yield json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
        finally:
            # Shield until the model thread finishes; its owner keeps all locks.
            await asyncio.shield(task)
    return StreamingResponse(stream(), media_type="application/x-ndjson")
