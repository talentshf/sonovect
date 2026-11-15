"""Official MCP SDK server over stdio. All tools call the same versioned API."""
from pathlib import Path
import os
from typing import Any, Literal
from pydantic import StrictBool, StrictInt
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError
from . import __version__
from .client import Client
from .models import Options


def create_server(client=None):
    service = client or Client()
    server = MCPServer("sonovect", version=__version__,
                       description="Audio jobs, FunASR transcripts and independent sound analysis")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @server.tool(annotations=read)
    def sonovect_ready(details: StrictBool = False) -> dict[str, Any]:
        """Read readiness and bounded failure codes without loading models or retrying jobs."""
        return service.readiness(details=details)

    @server.tool(annotations=read)
    def sonovect_capabilities() -> dict[str, Any]:
        """Read supported models, limits and optional acoustic analysis availability."""
        return service.request("GET", "/v1/capabilities").json()

    @server.tool(annotations=write)
    def sonovect_transcribe(path: str, language: str | None = None, prompt: str = "",
                            idempotency_key: str | None = None) -> dict[str, Any]:
        """Transcribe one local recording, returning text and its durable task ID.

        Uses the same configured input root as submit. On a wait timeout,
        recover the returned job ID; do not submit again.
        """
        raw_root = os.getenv("SONOVECT_MCP_INPUT_ROOT")
        if not raw_root:
            raise ToolError("MCP input root is not configured")
        root = Path(raw_root).expanduser().resolve(strict=True)
        selected = Path(path).expanduser().resolve(strict=True)
        if not root.is_dir() or not selected.is_relative_to(root) or not selected.is_file():
            raise ToolError("Audio file is outside the configured input root")
        return service.transcribe(selected, language=language, prompt=prompt, idempotency_key=idempotency_key)

    @server.tool(annotations=write)
    def sonovect_submit(paths: list[str], language: str | None = None, speakers: StrictBool = False,
                     analyze_sound: StrictBool = False, hotwords: list[str] | None = None,
                     idempotency_key: str | None = None, audio_track: StrictInt = 0, analyze_voice: StrictBool = False,
                     measure_voice: StrictBool = False, transcribe: StrictBool = True,
                     detect_speech: StrictBool = False, timestamps: Literal["none", "segment", "word"] = "none",
                     callback_url: str | None = None, translate_to: str | None = None, translation_context: str = "", classify_audio: StrictBool = False, classify_top_k: StrictInt = 5,
                     audio_question: str = "", alignment_text: str = "", channel_mode: Literal["mix","independent"] = "mix") -> dict[str, Any]:
        """Upload local audio/video within the operator-configured MCP input root; return a job ID.

        Poll sonovect_status with the returned ID. A wait is never a new submission.
        """
        raw_root = os.getenv("SONOVECT_MCP_INPUT_ROOT")
        if not raw_root:
            raise ToolError("MCP input root is not configured")
        root = Path(raw_root).expanduser().resolve(strict=True)
        if not root.is_dir() or not paths:
            raise ToolError("Invalid input root or file count")
        selected = []
        for raw in paths:
            path = Path(raw).expanduser().resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ToolError("Audio file is outside the configured input root")
            selected.append(path)
        maximum = service.request("GET", "/v1/capabilities").json().get("max_files", 16)
        if len(paths) > maximum:
            raise ToolError("File count exceeds this deployment's limit")
        return service.submit(selected, Options(language=language, speakers=speakers,
                              transcribe=transcribe, detect_speech=detect_speech, timestamps=timestamps,
                              translate_to=translate_to, translation_context=translation_context,
                              classify_audio=classify_audio, classify_top_k=classify_top_k, audio_question=audio_question, alignment_text=alignment_text,
                              analyze_sound=analyze_sound, analyze_voice=analyze_voice, hotwords=hotwords or [], audio_track=audio_track,
                              measure_voice=measure_voice, channel_mode=channel_mode), idempotency_key, callback_url)

    @server.tool(annotations=read)
    def sonovect_status(job_id: str) -> dict[str, Any]:
        """Read durable job state; partial and failed are not complete success."""
        return service.status(job_id)

    @server.tool(annotations=read)
    def sonovect_result(job_id: str, layer: Literal["result", "analysis", "translation", "manifest", "evidence", "attempts", "notification"] = "result",
                        format: Literal["json", "text", "srt"] = "json") -> dict[str, Any]:
        """Read a FunASR result list or its separate acoustic analysis/manifest.

        The data field contains the unmodified HTTP result. Status belongs to sonovect_status.
        """
        if layer != "result" and format != "json":
            raise ToolError("Only the result layer supports text and srt")
        response = service.request("GET", f"/v1/jobs/{job_id}/{layer}",
                                   params={"format": format} if layer == "result" else {})
        return {"data": response.json() if format == "json" else response.text}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    def sonovect_cancel(job_id: str) -> dict[str, Any]:
        """Cancel publication of a queued or running job. Active inference may finish internally."""
        return service.request("POST", f"/v1/jobs/{job_id}/cancel").json()

    @server.tool(annotations=write)
    def sonovect_retry(job_id: str) -> dict[str, Any]:
        """Explicitly reprocess a failed, partial or cancelled job while its inputs exist."""
        return service.request("POST", f"/v1/jobs/{job_id}/retry").json()

    return server


def main():
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
