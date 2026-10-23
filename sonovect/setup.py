"""Generate a reviewable deployment configuration without changing the host."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from . import __version__
from .assets import catalog, component_license_metadata


def selection(route="qwen", speech="1.7b", sound="ast", vad=None, native_revision="v2.0.4", voice="none", measurements=False, layout="compact"):
    if layout not in {"compact", "distributed"}:
        raise ValueError("unsupported_layout")
    vad = vad or ("fsmn" if route == "cpu" else "firered")
    if route not in {"qwen", "cpu"} or speech not in {"1.7b", "0.6b"} or sound not in {"none", "ast"} or voice not in {"none", "4b", "8b", "emotion2vec"} or vad not in {"firered", "fsmn"}:
        raise ValueError("unsupported_selection; use --sound none|ast and --voice none|4b|8b|emotion2vec")
    if route == "cpu" and (speech != "1.7b" or vad != "fsmn"):
        raise ValueError("cpu_speech_preset_uses_paraformer_fsmn_and_optional_cam")
    if native_revision not in {"v2.0.4", "v2.0.9"} or (route != "cpu" and native_revision != "v2.0.4"):
        raise ValueError("native_revision_requires_cpu_route_and_catalogued_revision")
    aliases = ["paraformer-v2.0.9" if native_revision == "v2.0.9" else "paraformer", "fsmn", "punc", "cam"] if route == "cpu" else ["qwen-" + speech, "aligner", "cam", "vad-placeholder"]
    if route == "qwen":aliases[-1] = "firered" if vad == "firered" else "fsmn"
    if sound == "ast":aliases.append("ast-events")
    if voice != "none":aliases.append("emotion2vec-base" if voice == "emotion2vec" else "moss-" + voice)
    models = catalog()
    env = {"SONOVECT_VERSION": __version__, "SONOVECT_MODELS_OFFLINE": "1",
           "SONOVECT_SOUND_ENABLED": str(sound == "ast").lower(),
           "SONOVECT_VOICE_ENABLED": str(voice != "none").lower(),
           "SONOVECT_VAD_BACKEND": vad,
           "SONOVECT_VOICE_BACKEND": "emotion2vec" if voice == "emotion2vec" else "moss",
           "SONOVECT_VOICE_URL": "http://speech-vocal:8085" if voice == "emotion2vec" else "http://speech-sound:8083",
           "SONOVECT_MEASUREMENTS_ENABLED": str(measurements).lower(),
           "SONOVECT_MEASUREMENTS_URL": "http://speech-measurements:8086",
           "COMPOSE_PROFILES": ",".join((["events"] if sound == "ast" else []) + (["vocal-cpu"] if voice == "emotion2vec" else ["voice"] if voice != "none" else []) + (["measurements"] if measurements else []))}
    analysis = sound == "ast" or voice == "emotion2vec" or measurements
    moss = voice in {"4b", "8b"}
    if layout == "compact":
        env.update(SONOVECT_LAYOUT="compact", SONOVECT_SOUND_URL="http://analysis:8084",
                   SONOVECT_MEASUREMENTS_URL="http://analysis:8086",
                   SONOVECT_VOICE_URL="http://analysis:8085" if voice == "emotion2vec" else "http://speech-sound:8083",
                   COMPOSE_PROFILES=",".join((["analysis"] if analysis else []) + (["voice"] if moss else [])),
                   SONOVECT_ANALYSIS_TARGET="analysis-worker" if sound == "ast" or voice == "emotion2vec" else "analysis-measurements",
                   SONOVECT_ANALYSIS_IMAGE="sonovect-analysis" if sound == "ast" or voice == "emotion2vec" else "sonovect-analysis-measurements")
    else:
        env["SONOVECT_LAYOUT"] = "distributed"
    if route == "cpu":env["SONOVECT_MODEL_REVISION"] = native_revision
    else:
        for prefix, alias in [("QWEN_ASR", "qwen-" + speech), ("QWEN_ALIGNER", "aligner")]:
            env[prefix + "_MODEL"] = models[alias]["repo_id"]
            env[prefix + "_REVISION"] = models[alias]["revision"]
        env.update(QWEN_GPU_BUDGET_MIB="8192", GPU_RESERVE_MIB="1024")
    if voice not in {"none", "emotion2vec"}:
        model = models["moss-" + voice]
        env.update(MOSS_AUDIO_MODEL=model["repo_id"], MOSS_AUDIO_REVISION=model["revision"],
                   MOSS_GPU_BUDGET_MIB="19456" if voice == "8b" else "12288", MOSS_MIN_FREE_GIB="20" if voice == "8b" else "10")
    return {"schema_version": "sonovect/deployment-selection-v1", "version": __version__,
            "route": route, "layout": layout,
            "compose_file": "deploy/compose." + ("distributed." if layout == "distributed" else "") + ("qwen." if route == "qwen" else "") + "yml",
            "container_count": (2 + int(analysis) + int(moss)) if layout == "compact" else ((2 if route == "cpu" else 5) + int(sound == "ast") + int(voice != "none") + int(measurements)),
            "speech": "paraformer" if route == "cpu" else speech,
            "sound": sound, "voice": voice, "vad": vad,
            "measurements": measurements, "measurement_model_download_bytes": 0,
            **component_license_metadata(aliases),
            "experimental": speech == "0.6b" or voice != "none" or native_revision == "v2.0.9",
            "models": {k: models[k] for k in aliases},
            "download_bytes": sum(models[k]["bytes"] for k in aliases), "environment": env}


def main(argv=None):
    p = argparse.ArgumentParser(description="Select models, show storage needs, generate .env; never installs host tools")
    p.add_argument("--route", choices=["cpu", "qwen"], default="qwen")
    p.add_argument("--layout", choices=["compact", "distributed"], default="compact", help="Default: 2 base containers plus selected analysis/MOSS; distributed is for independent scaling")
    p.add_argument("--speech", choices=["1.7b", "0.6b"], default="1.7b")
    p.add_argument("--sound", choices=["none", "ast"], default="ast", help="Independent CPU event classification")
    p.add_argument("--voice", choices=["none", "4b", "8b", "emotion2vec"], default="none", help="Experimental vocal backend: CPU emotion2vec or GPU MOSS; off by default")
    p.add_argument("--measurements", action=argparse.BooleanOptionalAction, default=False,
                   help="Independent weight-free pitch/energy; off unless selected")
    p.add_argument("--vad", choices=["firered", "fsmn"], help="Default: FireRed for Qwen, FSMN for CPU")
    p.add_argument("--native-revision", choices=["v2.0.4", "v2.0.9"], default="v2.0.4")
    p.add_argument("--write", type=Path, help="New .env path; refuses to overwrite")
    p.add_argument("--interactive", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.interactive:
            a.route = input("Route [qwen/cpu] (qwen): ").strip() or "qwen"
            if a.route == "qwen":
                a.speech = input("Speech [1.7b/0.6b experimental] (1.7b): ").strip() or "1.7b"
                a.vad = input("VAD [firered/fsmn] (firered): ").strip() or "firered"
        if a.interactive:
            a.sound = input("Events [ast/none] (ast): ").strip() or "ast"
            a.voice = input("Experimental vocal analysis [none/emotion2vec/4b/8b] (none): ").strip() or "none"
        value = selection(a.route, a.speech, a.sound, a.vad, a.native_revision, a.voice, a.measurements, a.layout)
        if a.write:
            env = {**value["environment"], "SONOVECT_TOKEN": secrets.token_urlsafe(32)}
            fd = os.open(a.write, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write("# Generated by sonovect setup; keep this file private.\n")
                f.write("\n".join(k + "=" + v for k, v in env.items()) + "\n")
            value["configuration_written"] = str(a.write)
        print(json.dumps(value, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
