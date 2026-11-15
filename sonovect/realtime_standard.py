"""OpenAI transcription sessions using the existing owner of the speech models."""
import asyncio
import base64
import binascii
import copy
import hmac
import json
from pathlib import Path
import tempfile
import time
import uuid
import wave

from fastapi import WebSocket, WebSocketDisconnect

from .backends import SpeechBackend
from .models import Options
from .vad import NeuralTurns, scores as vad_scores, turn_detection


def session_options(value, settings):
    if not isinstance(value, dict) or value.get("type", "transcription") != "transcription":
        raise ValueError("transcription_session_required")
    if set(value) - {"type", "audio", "include"} or value.get("include"):
        raise ValueError("unsupported_session_parameter")
    audio = value.get("audio") or {}
    if set(audio) - {"input"}:
        raise ValueError("unsupported_audio_parameter")
    source = audio.get("input") or {}
    if set(source) - {"format", "transcription", "turn_detection", "noise_reduction"}:
        raise ValueError("unsupported_audio_input_parameter")
    if source.get("format", {"type": "audio/pcm", "rate": 24000}) != {"type": "audio/pcm", "rate": 24000}:
        raise ValueError("pcm_24khz_mono_required")
    turn_detection(source.get("turn_detection"),settings)
    if source.get("noise_reduction") is not None:
        raise ValueError("noise_reduction_not_supported")
    transcription = source.get("transcription") or {}
    if not isinstance(transcription, dict) or set(transcription) - {"model", "language", "languages", "prompt", "keywords"}:
        raise ValueError("unsupported_transcription_parameter")
    if transcription.get("model", settings.transcription_model) != settings.transcription_model:
        raise ValueError("model_not_available")
    languages = transcription.get("languages") or []
    if not isinstance(languages, list) or len(languages) > 16 or any(not isinstance(x, str) or not x or len(x) > 32 for x in languages):
        raise ValueError("invalid_language_hints")
    if languages and transcription.get("language"):
        raise ValueError("select_one_language_hint_form")
    context = transcription.get("prompt", "")
    if len(languages) > 1:
        context = context + "\nExpected languages: " + ", ".join(languages)
    return Options(language=transcription.get("language") or (languages[0] if len(languages) == 1 else None),
                   context=context, hotwords=transcription.get("keywords") or [])


def merge_session(previous,current):
    if not isinstance(current,dict):raise ValueError("invalid_session_update")
    result=copy.deepcopy(previous) if isinstance(previous,dict) else {}
    for key,value in current.items():
        result[key]=merge_session(result.get(key,{}),value) if isinstance(value,dict) else copy.deepcopy(value)
    return result


def configuration(settings, options, identity, detection=None):
    transcription = {"model": settings.transcription_model, "prompt": options.context}
    if options.language:
        transcription["language"] = options.language
    if options.hotwords:
        transcription["keywords"] = options.hotwords
    return {"id": identity, "type": "transcription", "audio": {"input": {
        "format": {"type": "audio/pcm", "rate": 24000}, "transcription": transcription,
        "turn_detection": detection, "noise_reduction": None}}}


def capability(settings):
    return {"enabled": settings.realtime_enabled, "path": "/v1/realtime?intent=transcription",
            "protocol": "openai-realtime-transcription", "model": settings.transcription_model,
            "model_owner": "shared-speech-provider", "sample_rate": 24000, "channels": 1,
            "encoding": "pcm_s16le", "turn_detection": [None]+(["server_vad"] if settings.realtime_vad_enabled else []), "commit": "client-or-neural-vad", "default_turn_detection":"server_vad" if settings.realtime_vad_enabled else None,
            "partial_semantics": "append-delta-per-committed-item", "max_seconds": settings.realtime_max_seconds,
            "max_turn_seconds": settings.realtime_max_turn_seconds, "max_sessions": settings.realtime_max_sessions,
            "retention": "ephemeral; client-owned-results", "resume": False, "automatic_retry": False}


def install(app, settings, backend=None, vad=None):
    engine = backend or SpeechBackend(settings)
    score = vad or (lambda pcm,rate:vad_scores(settings,pcm,rate))
    slots = asyncio.Semaphore(settings.realtime_max_sessions)
    app.state.audio_slots = slots

    @app.websocket("/v1/realtime")
    async def realtime(ws: WebSocket):
        credentials = ws.headers.getlist("authorization")
        scheme, _, token = credentials[0].partition(" ") if len(credentials) == 1 else ("", "", "")
        if (scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), settings.token.encode())
                or not settings.realtime_enabled or ws.query_params.get("intent") != "transcription"):
            await ws.close(code=1008)
            return
        if ws.query_params.get("model", settings.transcription_model) != settings.transcription_model:
            await ws.close(code=1008, reason="model_not_available")
            return
        await ws.accept()
        if slots.locked():
            await ws.send_json({"type": "error", "event_id": "event_" + uuid.uuid4().hex,
                "error": {"type": "server_error", "code": "realtime_busy", "message": "Realtime capacity is full"}})
            await ws.close(code=1013)
            return
        await slots.acquire()
        identity, options = "sess_" + uuid.uuid4().hex, Options()
        send_lock, turns = asyncio.Lock(), asyncio.Queue(maxsize=4)
        closed, active = False, False
        buffer, previous_item = bytearray(), None
        detection=turn_detection({"type":"server_vad"},settings) if settings.realtime_vad_enabled else None
        detector=NeuralTurns(24000,detection,settings.realtime_max_turn_seconds) if detection else None
        active_item,received_samples=None,0
        started = time.monotonic()

        async def send(kind, **value):
            nonlocal closed
            if not closed:
                async with send_lock:
                    try:
                        await ws.send_json({"type": kind, "event_id": "event_" + uuid.uuid4().hex, **value})
                    except (WebSocketDisconnect, RuntimeError):
                        closed = True

        async def commit(pcm,item=None):
            nonlocal previous_item
            if len(pcm)<4800:raise ValueError("input_audio_buffer_too_small")
            if turns.full():raise ValueError("realtime_turn_queue_full")
            item=item or "item_"+uuid.uuid4().hex
            await send("input_audio_buffer.committed",item_id=item,previous_item_id=previous_item)
            await send("conversation.item.created",previous_item_id=previous_item,item={"id":item,"type":"message","role":"user","status":"completed","content":[{"type":"input_audio","transcript":None}]})
            turns.put_nowait((item,bytes(pcm),copy.deepcopy(options)));previous_item=item

        async def process(item_id, pcm, selected):
            updates, loop = asyncio.Queue(), asyncio.get_running_loop()
            def progress(value):
                loop.call_soon_threadsafe(updates.put_nowait, value.get("text", ""))
            with tempfile.TemporaryDirectory(prefix="realtime-", dir=settings.data_dir) as folder:
                path = Path(folder)/"audio.wav"
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
                    output.writeframes(pcm)
                path.chmod(0o600)
                task = asyncio.create_task(asyncio.to_thread(engine.process_stream, path, item_id, selected.wire(), progress))
                previous = ""
                try:
                    while not task.done() or not updates.empty():
                        try:
                            text = await asyncio.wait_for(updates.get(), .05)
                        except TimeoutError:
                            continue
                        if not isinstance(text, str) or not text.startswith(previous):
                            raise ValueError("non_monotonic_transcription")
                        if text != previous:
                            await send("conversation.item.input_audio_transcription.delta", item_id=item_id, content_index=0, delta=text[len(previous):])
                            previous = text
                    recognition = await asyncio.shield(task)
                    text = recognition.transcript["text"]
                    if not text.startswith(previous):
                        raise ValueError("non_monotonic_transcription")
                    if text != previous:
                        await send("conversation.item.input_audio_transcription.delta", item_id=item_id, content_index=0, delta=text[len(previous):])
                    await send("conversation.item.input_audio_transcription.completed", item_id=item_id, content_index=0,
                               transcript=text, usage={"type": "duration", "seconds": len(pcm)/48000})
                finally:
                    # Never delete an input or free a session slot while its HTTP/model thread is using it.
                    if not task.done():
                        try:
                            await asyncio.shield(task)
                        except Exception:
                            pass

        async def consume():
            nonlocal active
            while True:
                value = await turns.get()
                if value is None:
                    return
                if closed:
                    continue
                item_id, pcm, selected = value
                active = True
                try:
                    await process(item_id, pcm, selected)
                except Exception:
                    await send("conversation.item.input_audio_transcription.failed", item_id=item_id, content_index=0,
                               error={"type": "server_error", "code": "transcription_failed", "message": "Transcription failed"})
                finally:
                    active = False

        consumer = asyncio.create_task(consume())
        try:
            await send("session.created", session=configuration(settings, options, identity,detection))
            while time.monotonic() - started < settings.realtime_max_seconds:
                try:
                    message = await asyncio.wait_for(ws.receive_text(), settings.realtime_idle_seconds)
                except TimeoutError:
                    if active or not turns.empty():
                        continue
                    await send("error", error={"type": "server_error", "code": "session_idle_timeout", "message": "Session idle timeout"})
                    break
                value = None
                try:
                    if len(message) > 300000:
                        raise ValueError("audio_frame_limit_exceeded")
                    value = json.loads(message)
                    if not isinstance(value, dict):
                        raise ValueError("invalid_event")
                    kind = value.get("type")
                    if kind == "session.update":
                        if buffer or (detector and detector.buffer):
                            raise ValueError("commit_or_clear_audio_before_session_update")
                        existing=configuration(settings,options,identity,detection)
                        existing.pop("id")
                        updated=merge_session(existing,value.get("session"))
                        candidate=session_options(updated,settings)
                        options=candidate
                        detection=turn_detection(updated.get("audio",{}).get("input",{}).get("turn_detection"),settings)
                        detector=NeuralTurns(24000,detection,settings.realtime_max_turn_seconds) if detection else None
                        if detector:detector.origin=detector.total=received_samples
                        await send("session.updated", session=configuration(settings, options, identity,detection))
                    elif kind == "input_audio_buffer.append":
                        pcm = base64.b64decode(value.get("audio", ""), validate=True)
                        if not pcm or len(pcm) % 2 or len(pcm) > 192000:
                            raise ValueError("invalid_pcm_frame")
                        if received_samples+len(pcm)//2>settings.realtime_max_seconds*24000:
                            raise ValueError("session_audio_limit_exceeded")
                        received_samples+=len(pcm)//2
                        if detector:
                            for event in await detector.feed(pcm,score):
                                if event[0]=="started":
                                    active_item="item_"+uuid.uuid4().hex
                                    await send("input_audio_buffer.speech_started",item_id=active_item,audio_start_ms=event[1])
                                else:
                                    await send("input_audio_buffer.speech_stopped",item_id=active_item,audio_end_ms=event[1])
                                    await commit(event[2],active_item);active_item=None
                            if len(detector.buffer)>settings.realtime_max_turn_seconds*48000:
                                await commit(bytes(detector.buffer),active_item);detector.clear();active_item=None
                        else:
                            if len(buffer)+len(pcm)>settings.realtime_max_turn_seconds*48000:
                                raise ValueError("commit_turn_before_audio_limit")
                            buffer.extend(pcm)
                    elif kind == "input_audio_buffer.clear":
                        buffer.clear()
                        if detector:detector.clear()
                        active_item=None
                        await send("input_audio_buffer.cleared")
                    elif kind == "input_audio_buffer.commit":
                        await commit(bytes(detector.buffer) if detector else bytes(buffer),active_item)
                        buffer.clear()
                        if detector:detector.clear()
                        active_item=None
                    else:
                        raise ValueError("unsupported_event_type")
                except (ValueError, TypeError, binascii.Error, AttributeError) as error:
                    code = str(error) if type(error) is ValueError else "invalid_realtime_request"
                    await send("error", error={"type": "invalid_request_error", "code": code,
                                               "message": code, "event_id": value.get("event_id") if isinstance(value, dict) else None})
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass
        finally:
            closed = True
            while not turns.empty():
                turns.get_nowait()
            turns.put_nowait(None)
            try:
                await asyncio.shield(consumer)
            finally:
                slots.release()
                try:
                    await ws.close()
                except (RuntimeError,WebSocketDisconnect):
                    pass
