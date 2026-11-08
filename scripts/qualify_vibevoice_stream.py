"""One bounded native-model/HTTP/CLI qualification on public sample audio.

Run in the optional GPU runtime, never in the production file worker. The
output directory owns a completion receipt; repeat invocations read it rather
than repeat completed inference. No service credential or private media is used.
"""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import wave

from fastapi import FastAPI
import torch
import uvicorn

from sonovect.assets import catalog, verify
from sonovect.cli import main as cli_main
from sonovect.config import Settings
from sonovect.realtime import install


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = args.output / "result.json"
    if receipt.exists():
        print(json.dumps({"already_completed": True, "receipt": str(receipt)})); return
    model = catalog()["vibevoice-stream-1.5b"]
    verify(args.model_path, model)
    token = secrets.token_urlsafe(32)
    settings = Settings(data_dir=args.output / "unused-jobs", token=token, realtime_enabled=True,
                        realtime_backend="vibevoice-1.5b", realtime_model_path=str(args.model_path))
    app = FastAPI(); install(app, settings)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws_max_size=64000))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    while not server.started and thread.is_alive(): time.sleep(0.02)
    torch.cuda.reset_peak_memory_stats()
    results = []
    try:
        for language, name in [("Chinese", "asr_zh.wav"), ("English", "asr_en.wav")]:
            source = "https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-ASR-Repo/" + name
            audio = args.output / name
            if not audio.exists():
                with urllib.request.urlopen(source, timeout=60) as response: audio.write_bytes(response.read())
            with wave.open(str(audio), "rb") as w:
                duration = w.getnframes() / w.getframerate()
                if not 0 < duration <= 60:
                    raise RuntimeError("public_sample_duration_changed")
                pcm16 = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
            original_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
            if not pcm16:
                converted = args.output / (name + ".pcm16.wav")
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio), "-ac", "1",
                                "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(converted)], check=True)
                audio = converted
            events_file = args.output / (name + ".events.json")
            previous = json.loads(events_file.read_text()) if events_file.exists() else None
            if previous and previous[-1].get("type") == "final" and previous[-1].get("text", "").strip():
                results.append({"source": source, "original_sha256": original_hash,
                                "input_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                                "duration_seconds": round(duration, 3), "reused_successful_events": True,
                                "elapsed_seconds": None, "first_nonempty_partial_seconds": None,
                                "language_hint": language, "includes_first_model_load": None,
                                "partial_count": sum(e["type"] == "partial" for e in previous),
                                "nonempty_before_finish": any(e["type"] == "partial" and e.get("text", "").strip() for e in previous),
                                "final_text": previous[-1]["text"], "speaker_segments": previous[-1].get("speaker_segments", [])})
                continue
            cold = app.state.realtime_engine.model is None
            started = time.monotonic()
            first_text_at = []
            class Capture(io.StringIO):
                def write(self, text):
                    if text.startswith('{"type":'):
                        event = json.loads(text)
                        if event.get("type") == "partial" and event.get("text", "").strip() and not first_text_at:
                            first_text_at.append(time.monotonic() - started)
                    return super().write(text)
            out = Capture()
            old = {k: os.environ.get(k) for k in ("SONOVECT_URL", "SONOVECT_TOKEN", "SONOVECT_TOKEN_FILE")}
            os.environ.update(SONOVECT_URL=f"http://127.0.0.1:{port}", SONOVECT_TOKEN=token, SONOVECT_TOKEN_FILE="")
            try:
                with redirect_stdout(out): status = cli_main(["stream", str(audio), "--language", language])
            finally:
                for key, value in old.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value
            elapsed = time.monotonic() - started
            events = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{')]
            if status or not events or events[-1].get("type") != "final" or not events[-1].get("text", "").strip() or (duration >= 4 and not first_text_at):
                raise RuntimeError("native_cli_transcription_failed")
            events_file.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n")
            results.append({"source": source, "original_sha256": original_hash,
                            "input_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                            "duration_seconds": round(duration, 3), "elapsed_seconds": round(elapsed, 3),
                            "language_hint": language,
                            "first_nonempty_partial_seconds": round(first_text_at[0], 3) if first_text_at else None,
                            "includes_first_model_load": cold,
                            "partial_count": sum(e["type"] == "partial" for e in events),
                            "nonempty_before_finish": any(e["type"] == "partial" and e.get("text", "").strip() for e in events),
                            "final_text": events[-1]["text"], "speaker_segments": events[-1].get("speaker_segments", [])})
    finally:
        server.should_exit = True; thread.join(10); sock.close()
    value = {"passed": True, "model": model["repo_id"], "revision": model["revision"],
             "device": torch.cuda.get_device_name(), "peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
             "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2, 1),
             "peak_scope": "current-process-cases-only; excludes-reused-case-timing-and-memory",
             "cases": results, "scope": "public-short-audio-native-cli-streaming; no long-session-or-quality-acceptance"}
    temporary = receipt.with_suffix(".tmp"); temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n"); temporary.replace(receipt)
    print(json.dumps({k: value[k] for k in ("passed", "peak_allocated_mib", "peak_reserved_mib")}))


if __name__ == "__main__":
    main()
