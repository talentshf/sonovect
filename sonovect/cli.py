"""Portable command line client. Standard output contains only result data."""
import argparse
import json
import sys
from .client import Client
from .models import Options
from . import __version__


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"setup", "models"}:
        if argv[0] == "setup":
            from .setup import main as operator_main
        else:
            from .assets import main as operator_main
        return operator_main(argv[1:])
    parser = argparse.ArgumentParser(prog="sonovect")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Select deployment models and generate private configuration")
    commands.add_parser("models", help="List, prepare or verify pinned model assets")
    submit = commands.add_parser("submit", help="Upload audio or video soundtracks and create a durable job")
    submit.add_argument("files", nargs="+")
    submit.add_argument("--language")
    submit.add_argument("--no-speakers", action="store_true")
    submit.add_argument("--analyze-sound", action="store_true", help="AST environment events only")
    submit.add_argument("--analyze-voice", action="store_true", help="Deployment-selected experimental vocal observations")
    submit.add_argument("--measure-voice", action=argparse.BooleanOptionalAction, default=False,
                        help="Independent weight-free pitch/energy; off unless explicitly requested")
    submit.add_argument("--hotword", action="append", default=[])
    submit.add_argument("--audio-track", type=int, default=0, help="Zero-based audio stream index (default: 0)")
    submit.add_argument("--idempotency-key")
    submit.add_argument("--wait", action="store_true")
    for name in ("status", "wait", "cancel", "retry", "result", "analysis", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("job_id")
        if name == "result":
            sub.add_argument("--format", choices=["json", "text", "srt"], default="json")
        if name == "export":
            sub.add_argument("directory")
        if name == "wait":
            sub.add_argument("--timeout", type=float, default=7200)
    commands.add_parser("capabilities")
    commands.add_parser("ready", help="Check service/worker readiness without loading models")
    args = parser.parse_args(argv)
    client = None
    try:
        client = Client()
        if args.command == "submit":
            selected = Options(language=args.language, speakers=not args.no_speakers,
                               analyze_sound=args.analyze_sound, analyze_voice=args.analyze_voice, hotwords=args.hotword, audio_track=args.audio_track,
                               measure_voice=args.measure_voice)
            value = client.submit(args.files, selected, args.idempotency_key)
            if args.wait:
                value = client.wait(value["id"])
        elif args.command == "status":
            value = client.status(args.job_id)
        elif args.command == "wait":
            value = client.wait(args.job_id, timeout=args.timeout)
        elif args.command == "export":
            value = client.export(args.job_id, args.directory)
        elif args.command in {"cancel", "retry"}:
            value = client.request("POST", f"/v1/jobs/{args.job_id}/{args.command}").json()
        elif args.command in {"capabilities", "ready"}:
            value = client.request("GET", "/v1/capabilities" if args.command == "capabilities" else "/ready").json()
        else:
            response = client.request("GET", f"/v1/jobs/{args.job_id}/{args.command}",
                                      params={"format": args.format} if args.command == "result" else {})
            if args.command == "result" and args.format != "json":
                sys.stdout.write(response.text)
                return 0
            value = response.json()
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 2 if isinstance(value, dict) and value.get("status") in {"partial", "failed", "cancelled", "expired"} else 0
    except Exception as error:
        # Validation errors can include paths and submitted values.
        message = str(error) if isinstance(error, (RuntimeError, TimeoutError)) else type(error).__name__
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
