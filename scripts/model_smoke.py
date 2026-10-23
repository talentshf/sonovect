"""Optional real native-backend integration test using the upstream public sample."""
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.metadata
import json
import time
import urllib.request
from fastapi.testclient import TestClient
from sonovect.api import create_app
from sonovect.config import Settings
from sonovect.worker import Worker


def main():
    started = time.monotonic()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        audio = root / "upstream-example.wav"
        # Public sample used by FunASR's official quickstart, not a user recording.
        urllib.request.urlretrieve("https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/asr_example_zh.wav", audio)
        settings = Settings(data_dir=root / "jobs", token="synthetic-model-check-only")
        worker = Worker(settings)
        with TestClient(create_app(settings), headers={"Authorization": "Bearer " + settings.token}) as client:
            response = client.post("/v1/jobs", files={"files": ("sample.wav", audio.read_bytes(), "audio/wav")})
            response.raise_for_status()
            job_id = response.json()["id"]
            worker.run_once()
            status = worker.store.public(job_id)["status"]
            assert status == "succeeded", status
            result = client.get(f"/v1/jobs/{job_id}/result").json()
            assert len(result) == 1 and result[0]["text"]
            assert result[0].get("sentence_info"), "Expected native sentence output"
            report = {"backend": "funasr", "funasr_version": importlib.metadata.version("funasr"),
                      "status": status, "input": "official-upstream-sample", "private_audio_used": False,
                      "result_fields": sorted(result[0]), "sentence_count": len(result[0]["sentence_info"]),
                      "token_timestamp_count": len(result[0].get("timestamp", [])),
                      "elapsed_seconds": round(time.monotonic() - started, 2)}
            print(json.dumps(report, indent=2))
            Path("model-smoke-result.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
