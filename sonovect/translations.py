"""OpenAI English audio translation, keeping the source speech as its own artifact."""
import json
from typing import Annotated
from fastapi import Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from .models import Options
from .results import as_srt
from .waiting import await_job, job_headers


def install(app, settings, store, authenticate, admit_uploads):
    @app.post("/v1/audio/translations", dependencies=[Depends(authenticate)])
    async def translation(request: Request, file: Annotated[UploadFile, File()], model: Annotated[str, Form()],
                          prompt: Annotated[str, Form()] = "", response_format: Annotated[str, Form()] = "json",
                          temperature: Annotated[float, Form()] = 0,
                          idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None):
        if not settings.translation_url:
            raise HTTPException(400, "translation_not_configured")
        if model != settings.transcription_model:
            raise HTTPException(400, "model_not_available")
        form = await request.form()
        if set(form) - {"file", "model", "prompt", "response_format", "temperature"}:
            raise HTTPException(400, "unsupported_parameter")
        if len(form.getlist("file")) != 1:
            raise HTTPException(400, "exactly_one_file_required")
        if response_format not in {"json", "text", "srt", "vtt"}:
            raise HTTPException(400, "translation_response_format_not_supported")
        if temperature != 0:
            raise HTTPException(400, "temperature_not_supported")
        try:
            options = Options(translate_to="en", translation_context=prompt,
                              timestamps="segment" if response_format in {"srt", "vtt"} else "none")
        except ValueError:
            raise HTTPException(400, "invalid_translation_options") from None
        response = await admit_uploads(files=[file], options=options.model_dump_json(), idempotency_key=idempotency_key)
        job_id = json.loads(response.body)["id"]
        headers = job_headers(job_id)
        job = await await_job(request, settings, store, job_id, "translation")
        if isinstance(job, Response):
            return job
        values = job["translation"] or []
        if job["state"] != "succeeded" or len(values) != 1 or values[0].get("status") != "completed":
            raise HTTPException(503, "translation_" + job["state"], headers=headers)
        if response_format == "json":
            return JSONResponse({"text": values[0]["text"]}, headers=headers)
        if response_format == "text":
            return Response(values[0]["text"], media_type="text/plain; charset=utf-8", headers=headers)
        try:
            subtitle = as_srt([{"sentence_info": values[0]["segments"]}])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "translation_timing_unavailable", headers=headers) from None
        if response_format == "vtt":
            import re
            subtitle = "WEBVTT\n\n" + re.sub(r"^(\d{2}:\d{2}:\d{2}),(\d{3})( --> \d{2}:\d{2}:\d{2}),(\d{3})$",
                                                 r"\1.\2\3.\4", subtitle, flags=re.MULTILINE)
        return Response(subtitle, media_type="text/vtt" if response_format == "vtt" else "application/x-subrip", headers=headers)
