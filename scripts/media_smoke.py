"""Isolated real-model audio/video smoke; never touches the installed job database.

Use a short consented/open audio clip and an explicitly selected bundled provider.
Optional reference text is used only after inference, never as a model hint.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sonovect import __version__
from sonovect.api import create_app
from sonovect.client import Client
from sonovect.config import Settings
from sonovect.media import prepare_media
from sonovect.models import Options
from sonovect.worker import Worker


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def edits(expected, actual):
    row = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        next_row = [i]
        for j, right in enumerate(actual, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j-1] + (left != right)))
        row = next_row
    return row[-1]


async def mcp_check(url, token, job, expected, subtitle):
    params = StdioServerParameters(command=sys.executable, args=["-m", "sonovect.mcp_server"],
        env={**os.environ, "SONOVECT_URL": url, "SONOVECT_TOKEN": token})
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            for format, value in (("json", expected), ("text", expected[0]["text"]), ("srt", subtitle)):
                result = await session.call_tool("sonovect_result", {"job_id": job, "format": format})
                assert not result.is_error and result.structured_content["data"] == value, format
    return {"json": True, "text": True, "srt": True}


def run(source, provider_url, reference, language=None):
    with TemporaryDirectory(prefix="sonovect-media-smoke-") as raw:
        root = Path(raw)
        settings = Settings(data_dir=root, token=secrets.token_urlsafe(32), backend="speech", provider_url=provider_url)
        with prepare_media(source, {}, settings) as (audio, metadata):
            if metadata["duration_ms"] > 30000:
                raise ValueError("Supply a short audio clip of at most 30 seconds")
            duration = math.ceil(metadata["duration_ms"] / 1000 + 2)
            video = root / "two-tracks.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                f"color=size=16x16:rate=1:duration={duration}", "-itsoffset", "2", "-i", str(audio),
                "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono:d={duration}",
                "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "aac",
                "-t", str(duration), str(video)], check=True, timeout=30, stdout=subprocess.DEVNULL)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("Candidate API did not start")
            time.sleep(0.05)
        client = Client(url=url, token=settings.token)
        worker = Worker(settings)
        report = {"version": __version__, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "scope": "one-short-clip-and-two-video-track-variants", "cases": []}
        try:
            with httpx.Client(trust_env=False, timeout=10) as discovery:
                report["provider_version"] = discovery.get(provider_url + "/health").json().get("version")
            for name, path, selected in (
                ("audio", source, Options(language=language, speakers=False)),
                ("video-speech-sound", video, Options(language=language, speakers=True, analyze_sound=True)),
                ("video-silent-track", video, Options(language=language, speakers=False, audio_track=1))):
                job = client.submit([path], selected)
                started = time.monotonic()
                assert worker.run_once()
                final = client.status(job["id"])
                assert final["status"] == "succeeded", final
                result = client.request("GET", f"/v1/jobs/{job['id']}/result").json()
                analysis = client.request("GET", f"/v1/jobs/{job['id']}/analysis").json()
                assert analysis[0]["status"] == ("completed" if selected.analyze_sound else "not_requested")
                case = {"case": name, "job": final, "result": result, "analysis": analysis,
                        "elapsed_seconds": round(time.monotonic() - started, 3)}
                if name == "video-silent-track":
                    assert result[0]["text"] == "", result
                else:
                    assert result[0]["text"]
                    case["word_edits"] = edits(words(reference), words(result[0]["text"])) if reference else None
                    case["reference_words"] = len(words(reference)) if reference else None
                    srt = client.request("GET", f"/v1/jobs/{job['id']}/result", params={"format": "srt"}).text
                    case["srt"] = srt
                    manifest = client.export(job["id"], root / (name + "-export"))
                    case["export_verified"] = bool(manifest["artifacts"])
                    if name == "audio":
                        baseline_start = result[0]["sentence_info"][0]["start"]
                        assert all("spk" not in sentence for sentence in result[0].get("sentence_info", []))
                    else:
                        assert 1900 <= final["sources"][0]["media"]["leading_silence_ms"] <= 2100
                        delta = result[0]["sentence_info"][0]["start"] - baseline_start
                        assert 1500 <= delta <= 2500, delta
                        case["speech_start_shift_ms"] = delta
                        case["mcp_formats"] = asyncio.run(mcp_check(url, settings.token, job["id"], result, srt))
                        env = {**os.environ, "SONOVECT_URL": url, "SONOVECT_TOKEN": settings.token}
                        cli = subprocess.run([sys.executable, "-m", "sonovect.cli", "result", job["id"], "--format", "srt"],
                                             env=env, capture_output=True, text=True, timeout=30, check=True)
                        assert cli.stdout == srt
                        case["cli_srt"] = True
                report["cases"].append(case)
            report["accepted"] = True
            return report
        finally:
            client.close()
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--provider-url", required=True)
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--language", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.source, args.provider_url, args.reference_text, args.language)
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(data)
    else:
        print(data, end="")


if __name__ == "__main__":
    main()
