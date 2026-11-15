"""Standard file transcription over the same durable job admission and worker."""
import asyncio
import json
import time
from typing import Annotated

from fastapi import Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .models import Options
from .results import as_srt
from .store import TERMINAL
from .waiting import await_job, job_headers


def install(app, settings, store, authenticate, admit_uploads):
    @app.get("/v1/models", dependencies=[Depends(authenticate)])
    def models():
        data=[{"id":settings.transcription_model,"object":"model","created":0,"owned_by":"sonovect",
               "sonovect":{"tasks":["transcription"]+(["translation"] if settings.translation_url else [])}}]
        if settings.understanding_url:
            data.append({"id":settings.understanding_model,"object":"model","created":0,"owned_by":"sonovect","sonovect":{"tasks":["audio-understanding"],"output":["text"]}})
        if settings.sound_enabled and settings.sound_url:
            data.append({"id":"ast-audioset","object":"model","created":0,"owned_by":"sonovect","sonovect":{"tasks":["audio-classification"],"path":"/models/ast-audioset"}})
        return {"object":"list","data":data}

    @app.post("/v1/audio/transcriptions", dependencies=[Depends(authenticate)])
    async def transcribe(
        request: Request,
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()],
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str, Form()] = "",
        response_format: Annotated[str, Form()] = "json",
        temperature: Annotated[float, Form()] = 0,
        stream: Annotated[bool, Form()] = False,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None,
    ):
        if model != settings.transcription_model:
            raise HTTPException(400, "model_not_available")
        form = await request.form()
        allowed = {"file", "model", "language", "prompt", "response_format", "temperature", "stream", "timestamp_granularities[]"}
        if set(form) - allowed:
            raise HTTPException(400, "unsupported_parameter")
        if len(form.getlist("file")) != 1:
            raise HTTPException(400, "exactly_one_file_required")
        if response_format not in {"json", "text", "srt", "vtt", "verbose_json", "diarized_json"}:
            raise HTTPException(400, "response_format_not_supported")
        granularities = form.getlist("timestamp_granularities[]")
        if response_format == "verbose_json":
            if granularities != ["word"] or settings.backend != "speech":
                raise HTTPException(400, "verbose_json_requires_supported_word_granularity")
        elif granularities:
            raise HTTPException(400, "timestamp_granularities_require_verbose_json")
        if stream and (response_format != "json" or settings.backend != "speech"):
            raise HTTPException(400, "file_streaming_requires_speech_json")
        if temperature != 0:
            raise HTTPException(400, "temperature_not_supported")
        if prompt and settings.backend != "speech":
            raise HTTPException(400, "prompt_not_supported_by_model")
        try:
            options = Options(language=None if language == "auto" else language, context=prompt,
                              speakers=response_format == "diarized_json",
                              timestamps="word" if response_format in {"srt", "vtt", "verbose_json", "diarized_json"} else "none")
        except ValueError:
            raise HTTPException(400, "invalid_transcription_options") from None
        admitted = await admit_uploads(files=[file], options=options.model_dump_json(),
                                      idempotency_key=idempotency_key)
        job_id = json.loads(admitted.body)["id"]
        headers = job_headers(job_id)
        if stream:
            return StreamingResponse(transcription_events(request, settings, store, job_id), media_type="text/event-stream",
                                     headers={**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        job = await await_job(request, settings, store, job_id)
        if isinstance(job, Response):
            return job
        if job["state"] != "succeeded":
            code = "result_expired" if job["state"] == "expired" else "transcription_" + job["state"]
            raise HTTPException(410 if job["state"] == "expired" else 503, code, headers=headers)
        values = job["result"] or []
        if len(values) != 1:
            raise HTTPException(503, "invalid_transcription_result", headers=headers)
        text = values[0]["text"]
        if response_format == "text":
            return Response(text, media_type="text/plain; charset=utf-8", headers=headers)
        if response_format in {"srt", "vtt"}:
            try:
                subtitle = as_srt(values, job["evidence"])
            except ValueError:
                raise HTTPException(422, "subtitle_timing_unavailable", headers=headers) from None
            if response_format == "vtt":
                import re
                subtitle = "WEBVTT\n\n" + re.sub(r"^(\d{2}:\d{2}:\d{2}),(\d{3})( --> \d{2}:\d{2}:\d{2}),(\d{3})$",
                                                     r"\1.\2\3.\4", subtitle, flags=re.MULTILINE)
            return Response(subtitle, media_type="text/vtt" if response_format == "vtt" else "application/x-subrip", headers=headers)
        duration_ms = job["sources"][0].get("media", {}).get("duration_ms")
        if response_format in {"diarized_json", "verbose_json"} and (type(duration_ms) is not int or duration_ms < 0):
            raise HTTPException(503, "media_duration_unavailable", headers=headers)
        duration = duration_ms / 1000 if duration_ms is not None else None
        if response_format == "diarized_json":
            segments = []
            for index, sentence in enumerate(values[0].get("sentence_info") or []):
                if "spk" not in sentence:
                    raise HTTPException(422, "diarization_evidence_unavailable", headers=headers)
                segments.append({"id": str(index), "type": "transcript.text.segment", "speaker": "speaker_" + str(sentence["spk"]),
                                 "start": sentence["start"] / 1000, "end": sentence["end"] / 1000, "text": sentence["text"]})
            if text and not segments:
                raise HTTPException(422, "diarization_evidence_unavailable", headers=headers)
            return JSONResponse({"task": "transcribe", "duration": duration, "text": text, "segments": segments}, headers=headers)
        if response_format == "verbose_json":
            evidence = (job["evidence"] or [{}])[0]
            sentences = (evidence.get("transcripts") or [{}])[0].get("sentences", [])
            if any(s.get("text", "").strip() and not s.get("words") for s in sentences):
                raise HTTPException(422, "word_alignment_unavailable", headers=headers)
            words = [{"word": w["text"], "start": w["begin_time"] / 1000, "end": w["end_time"] / 1000}
                     for sentence in sentences for w in sentence.get("words", [])]
            if text and not words:
                raise HTTPException(422, "word_alignment_unavailable", headers=headers)
            return JSONResponse({"task": "transcribe", "language": evidence.get("language") or language or "unknown",
                                 "duration": duration, "text": text, "words": words}, headers=headers)
        return JSONResponse({"text": text}, headers=headers)


async def transcription_events(request, settings, store, job_id):
    """Forward actual completed ASR chunks, then the authoritative stored result."""
    cursor, previous, heartbeat = 0, "", time.monotonic()
    def frame(value):
        return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"
    while not await request.is_disconnected():
        rows = await asyncio.to_thread(store.events, job_id, cursor)
        for event in rows:
            cursor = event["id"]
            if event["type"] != "transcript.partial":
                continue
            text = event["data"].get("text", "")
            if not isinstance(text, str) or not text.startswith(previous):
                yield frame({"type": "error", "code": "non_monotonic_transcription", "message": "Read the persisted job result", "job_id": job_id})
                return
            if text != previous:
                yield frame({"type": "transcript.text.delta", "delta": text[len(previous):]})
                previous = text
        job = await asyncio.to_thread(store.get, job_id)
        if job["state"] in TERMINAL and len(rows) < 500:
            if job["state"] == "succeeded" and len(job["result"] or []) == 1:
                text = job["result"][0]["text"]
                if not text.startswith(previous):
                    yield frame({"type": "error", "code": "non_monotonic_transcription", "message": "Read the persisted job result", "job_id": job_id})
                    return
                if text != previous:
                    yield frame({"type": "transcript.text.delta", "delta": text[len(previous):]})
                yield frame({"type": "transcript.text.done", "text": text})
            else:
                yield frame({"type": "error", "code": "transcription_" + job["state"], "message": "Transcription did not complete", "job_id": job_id})
            return
        if time.monotonic() - heartbeat >= 15:
            heartbeat = time.monotonic()
            yield ": heartbeat\n\n"
        await asyncio.sleep(.05)
