#!/usr/bin/env python3
"""Prepare exactly the models selected by a resolved Compose configuration.

Uses the operator's Docker context/authentication. Does not start public services,
replace drivers or expose tokens in output. Build/pull images before preparation.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sonovect.assets import catalog, component_license_metadata


def check_capacity(cmd, tasks):
    """Inspect every selected cache before the first download, across shared volumes."""
    volumes = {}
    for service, entry, aliases, extra in tasks:
        if not aliases:
            continue
        raw = subprocess.check_output(cmd + ["run", "--rm", "--no-deps", service] +
                                      entry + ["plan"] + aliases + extra, text=True)
        for row in json.loads(raw):
            group = volumes.setdefault(row["filesystem"], {"free_bytes": row["free_bytes"],
                "missing_bytes": 0, "largest_missing_file": 0, "models": []})
            group["free_bytes"] = min(group["free_bytes"], row["free_bytes"])
            group["missing_bytes"] += row["missing_bytes"]
            group["largest_missing_file"] = max(group["largest_missing_file"], row["largest_missing_file"])
            group["models"].append(row["alias"])
    for group in volumes.values():
        # One largest-file allowance covers SDK staging/copy; 1 GiB remains free.
        required = group["missing_bytes"] + group["largest_missing_file"] + 1024**3 if group["missing_bytes"] else 0
        if group["free_bytes"] < required:
            raise ValueError("insufficient_model_disk_space: models=" + ",".join(group["models"]) +
                             " missing_bytes=" + str(group["missing_bytes"]) +
                             " required_with_reserve=" + str(required) +
                             " available_bytes=" + str(group["free_bytes"]))
    return list(volumes.values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compose", default="deploy/compose.qwen.yml")
    p.add_argument("--env-file", default="deploy/.env")
    p.add_argument("--context", help="Existing Docker context; omitted uses the current context")
    p.add_argument("--verify-only", action="store_true", help="No network or cache writes")
    p.add_argument("--plan", action="store_true", help="Print selected assets without preparing them")
    p.add_argument("--check-hardware", action="store_true", help="Probe selected containers' GPU, memory, cache access and disk before downloads")
    p.add_argument("--smoke-audio", type=Path, help="After API startup, upload a short consented speech sample and verify real inference/export")
    p.add_argument("--smoke-language", default="", help="Optional language hint for the acceptance sample")
    a = p.parse_args()
    docker = ["docker"] + (["--context", a.context] if a.context else [])
    cmd = docker + ["compose", "--env-file", a.env_file, "-f", a.compose]
    try:
        config = json.loads(subprocess.check_output(cmd + ["config", "--format", "json"], text=True))
        services = config["services"]
        lookup = {(v["repo_id"], v["revision"]): k for k, v in catalog().items()}
        tasks = []
        explicit = []
        compact = services.get("api", {}).get("environment", {}).get("SONOVECT_LAYOUT") == "compact"
        core = services["api"]["environment"]
        if compact:
            worker = services["worker"]["environment"]
            if worker.get("SONOVECT_BACKEND") == "speech":
                aliases = [lookup[(worker[k+"_MODEL"], worker[k+"_REVISION"])] for k in ["QWEN_ASR", "QWEN_ALIGNER"]]
                entry = ["python", "-c", "import os,sys; os.environ['HF_HOME']=os.getenv('QWEN_HF_HOME','/models/qwen/huggingface'); from sonovect.assets import main; raise SystemExit(main(sys.argv[1:]))"]
                tasks.append(("worker", entry, aliases, []))
                vad = "firered" if worker.get("VAD_BACKEND") == "firered" else "fsmn"
                aliases = ["cam", vad]
                if vad == "firered" and worker.get("FIRERED_VAD_ROOT"):
                    aliases.remove(vad)
                    explicit.append(("worker", vad, "import os,sys,json; sys.path.insert(0,'/opt/sonovect/providers/segmentation'); from firered_vad_adapter import verify_model; verify_model(os.environ['FIRERED_VAD_ROOT']); print(json.dumps(dict(model='firered',verified=True)))"))
                entry = ["python", "-c", "import os,sys; os.environ['MODELSCOPE_CACHE']=os.getenv('SEGMENTATION_CACHE','/models/segmentation'); os.environ['HF_HOME']=os.getenv('SEGMENTATION_HF_HOME','/models/segmentation/huggingface'); from sonovect.assets import main; raise SystemExit(main(sys.argv[1:]))"]
                tasks.append(("worker", entry, aliases, []))
            elif worker.get("SONOVECT_BACKEND") == "funasr":
                revision = worker.get("SONOVECT_MODEL_REVISION", "v2.0.4")
                if revision not in {"v2.0.4", "v2.0.9"}:raise ValueError("native_revision_not_in_catalog")
                tasks.append(("worker", ["sonovect", "models"], ["paraformer" if revision == "v2.0.4" else "paraformer-v2.0.9", "fsmn", "punc", "cam"], []))
            else:raise ValueError("unsupported_compact_speech_backend")
            cpu_voice = core.get("SONOVECT_VOICE_BACKEND") == "emotion2vec"
            for key, root_key, alias in [("SONOVECT_SOUND_ENABLED", "SOUND_EVENT_MODEL_ROOT", "ast-events"),
                                         ("SONOVECT_VOICE_ENABLED", "VOCAL_MODEL_ROOT", "emotion2vec-base")]:
                if key == "SONOVECT_VOICE_ENABLED" and not cpu_voice:continue
                if str(core.get(key, "false")).lower() not in {"true", "1", "yes"}:continue
                if "analysis" not in services:raise ValueError("selected_analysis_service_missing")
                environment=services["analysis"]["environment"]
                if str(environment.get(key,"false")).lower() not in {"true","1","yes"}:raise ValueError("analysis_capability_configuration_mismatch:"+key)
                aliases=[alias]
                if environment.get(root_key):
                    aliases=[];model=catalog()[alias]
                    code="import os,json; from sonovect.assets import verify_identity; verify_identity(os.environ["+repr(root_key)+"],"+repr(model["repo_id"])+","+repr(model["revision"])+"); print(json.dumps(dict(verified=True,source='configured-directory')))"
                    explicit.append(("analysis",alias,code))
                tasks.append(("analysis",["sonovect","models"],aliases,[]))
            if str(core.get("SONOVECT_MEASUREMENTS_ENABLED","false")).lower() in {"true","1","yes"}:
                if "analysis" not in services or str(services["analysis"]["environment"].get("SONOVECT_MEASUREMENTS_ENABLED","false")).lower() not in {"true","1","yes"}:raise ValueError("selected_measurements_module_missing")
            if not cpu_voice and str(core.get("SONOVECT_VOICE_ENABLED","false")).lower() in {"true","1","yes"}:
                if "speech-sound" not in services:raise ValueError("selected_moss_service_missing")
                e=services["speech-sound"]["environment"];alias=lookup[(e["MOSS_AUDIO_MODEL"],e["MOSS_AUDIO_REVISION"])];aliases=[alias]
                if e.get("MOSS_MODEL_ROOT"):
                    aliases=[];model=catalog()[alias]
                    code="import os,json; from sonovect_assets import verify_identity; verify_identity(os.environ['MOSS_MODEL_ROOT'],"+repr(model["repo_id"])+","+repr(model["revision"])+"); print(json.dumps(dict(verified=True,source='configured-directory')))"
                    explicit.append(("speech-sound",alias,code))
                tasks.append(("speech-sound",["python","sonovect_assets.py"],aliases,[]))
        else:
            if "speech-asr" in services:
                e = services["speech-asr"]["environment"]
                aliases = [lookup[(e[k + "_MODEL"], e[k + "_REVISION"])] for k in ["QWEN_ASR", "QWEN_ALIGNER"]]
                tasks.append(("speech-asr", ["python", "sonovect_assets.py"], aliases, []))
                seg = services["speech-segmentation"]["environment"]
                vad = "firered" if seg.get("VAD_BACKEND") == "firered" else "fsmn"
                aliases = ["cam", vad]
                if vad == "firered" and seg.get("FIRERED_VAD_ROOT"):
                    aliases.remove(vad)
                    explicit.append(("speech-segmentation", vad,
                        "import os,json; from firered_vad_adapter import verify_model; verify_model(os.environ['FIRERED_VAD_ROOT']); print(json.dumps(dict(model='firered',verified=True,source='configured-directory')))"))
                tasks.append(("speech-segmentation", ["python", "sonovect_assets.py"], aliases, []))
            elif services.get("worker", {}).get("environment", {}).get("SONOVECT_BACKEND") == "funasr":
                revision = services["worker"]["environment"].get("SONOVECT_MODEL_REVISION", "v2.0.4")
                native = "paraformer" if revision == "v2.0.4" else "paraformer-v2.0.9" if revision == "v2.0.9" else None
                if native is None:
                    raise ValueError("native_revision_not_in_catalog")
                tasks.append(("worker", ["sonovect", "models"], [native, "fsmn", "punc", "cam"], []))
            else:
                raise ValueError("external provider deployment: prepare models at that provider")
            core = services["api"]["environment"]
            if str(core.get("SONOVECT_MEASUREMENTS_ENABLED", "false")).lower() in {"true", "1", "yes"} and "speech-measurements" not in services:
                raise ValueError("selected_acoustic_profile_missing:speech-measurements")
            cpu_voice = core.get("SONOVECT_VOICE_BACKEND", "moss") == "emotion2vec"
            for enabled_key, service, root_key, identity in [
                ("SONOVECT_SOUND_ENABLED", "speech-events", "SOUND_EVENT_MODEL_ROOT", "ast-events"),
                ("SONOVECT_VOICE_ENABLED", "speech-vocal" if cpu_voice else "speech-sound", "VOCAL_MODEL_ROOT" if cpu_voice else "MOSS_MODEL_ROOT", "emotion2vec-base" if cpu_voice else None)]:
                if str(core.get(enabled_key, "false")).lower() not in {"true", "1", "yes"}:continue
                if service not in services:raise ValueError("selected_acoustic_profile_missing:"+service)
                e=services[service]["environment"]
                alias=identity or lookup[(e["MOSS_AUDIO_MODEL"],e["MOSS_AUDIO_REVISION"])]
                aliases=[alias]
                if e.get(root_key):
                    aliases=[]
                    model=catalog()[alias]
                    code="import os,json; from sonovect_assets import verify_identity; verify_identity(os.environ["+repr(root_key)+"],"+repr(model["repo_id"])+","+repr(model["revision"])+"); print(json.dumps(dict(verified=True,source='configured-directory')))"
                    explicit.append((service,alias,code))
                tasks.append((service,["python","sonovect_assets.py"],aliases,[]))
        selected = sorted({alias for _, _, aliases, _ in tasks for alias in aliases} | {a for _, a, _ in explicit})
        explicit_aliases = {a for _, a, _ in explicit}
        print(json.dumps({"selected_models": selected, "required_model_bytes": sum(catalog()[k]["bytes"] for k in selected),
                          "maximum_download_bytes": sum(catalog()[k]["bytes"] for k in selected if k not in explicit_aliases),
                          "explicit_model_aliases": sorted(explicit_aliases),
                          **component_license_metadata(selected),
                          "measurement_model_download_bytes": 0,
                          "offline": a.verify_only}, indent=2), flush=True)
        if not a.plan:
            # Explicit model roots must validate before any selected download.
            for service, _, code in explicit:
                subprocess.run(cmd + ["run", "--rm", "--no-deps", service, "python", "-c", code], check=True)
            if not a.verify_only:
                capacity = check_capacity(cmd, tasks)
                print("MODEL_STORAGE_PLAN=" + json.dumps(capacity), flush=True)
            if a.check_hardware:
                access = "os.R_OK" if a.verify_only else "os.W_OK"
                probe = ("import json,os,shutil; p='/models'; d=shutil.disk_usage(p); "
                         "v=dict(cache_writable=os.access(p,os.W_OK),disk_free_bytes=d.free,"
                         "ram_bytes=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')); "
                         "print(json.dumps(v)); assert os.access(p," + access + "), 'cache_not_accessible'")
                for service, _, _, _ in tasks:
                    subprocess.run(cmd + ["run", "--rm", "--no-deps", service, "python", "-c", probe], check=True)
                if any(t[0] in {"speech-asr", "speech-sound"} for t in tasks) or (compact and services["worker"]["environment"].get("SONOVECT_BACKEND") == "speech"):
                    gpu_probe = ("import torch,json,os; assert torch.cuda.is_available(),'cuda_unavailable'; "
                                 "free,total=torch.cuda.mem_get_info(); "
                                 "print(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,free_mib=free//2**20,total_mib=total//2**20))); "
                                 "budget=max(int(os.getenv('QWEN_GPU_BUDGET_MIB','8192')),int(os.getenv('MOSS_GPU_BUDGET_MIB','0'))); "
                                 "assert (budget+int(os.getenv('GPU_RESERVE_MIB','1024')))*2**20<=free,'insufficient_free_gpu_memory'")
                    for service in sorted({s for s in ["speech-asr", "speech-sound"] if s in {t[0] for t in tasks}} | ({"worker"} if compact and services["worker"]["environment"].get("SONOVECT_BACKEND") == "speech" else set())):
                        subprocess.run(cmd + ["run", "--rm", "--no-deps", service, "python", "-c", gpu_probe], check=True)
            for service, entry, aliases, extra in tasks:
                # MODELSCOPE_CACHE/HF_HOME belong to each role's existing volume.
                if aliases:
                    subprocess.run(cmd + ["run", "--rm", "--no-deps", service] + entry +
                                   ["verify" if a.verify_only else "prepare"] + aliases + extra, check=True)
            if a.smoke_audio:
                maximum = int(services["api"]["environment"].get("SONOVECT_MAX_UPLOAD_BYTES", 268435456))
                if not a.smoke_audio.is_file() or not 0 < a.smoke_audio.stat().st_size <= maximum:
                    raise ValueError("acceptance_sample_missing_empty_or_exceeds_upload_limit")
                smoke = '''import json,os,sys,tempfile
from pathlib import Path
from sonovect.client import Client
from sonovect.models import Options
with tempfile.TemporaryDirectory(prefix="deployment-acceptance-") as raw:
    p=Path(raw)/"sample.audio";p.write_bytes(sys.stdin.buffer.read());p.chmod(0o600)
    voice=os.getenv("SONOVECT_VOICE_ENABLED","false").lower() in {"1","true","yes"}
    sound=os.getenv("SONOVECT_SOUND_ENABLED","false").lower() in {"1","true","yes"}
    measure=os.getenv("SONOVECT_MEASUREMENTS_ENABLED","false").lower() in {"1","true","yes"}
    with_client=Client(url="http://127.0.0.1:8096")
    try:
        job=with_client.submit([p],Options(language=sys.argv[1] or None,analyze_sound=sound,analyze_voice=voice,measure_voice=measure))
        status=with_client.wait(job["id"])
        if status["status"]!="succeeded":raise RuntimeError("deployment_inference_failed:"+status["status"])
        result=with_client.request("GET","/v1/jobs/"+job["id"]+"/result").json()
        if not any(v.get("text","").strip() for v in result):raise RuntimeError("acceptance_sample_has_no_recognized_speech")
        analysis=with_client.request("GET","/v1/jobs/"+job["id"]+"/analysis").json()
        for item in analysis:
            for stage,enabled in [("events",sound),("vocal",voice),("measurements",measure)]:
                if enabled and item.get("stages",{}).get(stage,{}).get("status")!="completed":
                    raise RuntimeError("deployment_analysis_failed:"+stage)
            if measure and not item.get("measurements"):
                raise RuntimeError("acceptance_sample_has_no_speech_measurements")
        manifest=with_client.export(job["id"],Path(raw)/"export")
        print(json.dumps(dict(job_id=job["id"],status=status["status"],sound_requested=sound,measurements_requested=measure,export_verified=True,artifacts=manifest["artifacts"])))
    finally:with_client.close()
'''
                subprocess.run(cmd + ["exec", "-T", "api", "python", "-c", smoke, a.smoke_language],
                               input=a.smoke_audio.read_bytes(), check=True)
        return 0
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
