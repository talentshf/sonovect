"""Bounded provider probe with useful Docker health output."""
import asyncio
import json
import sys
from health_probe import probe

async def main():
    value = await probe("http://127.0.0.1:" + sys.argv[1], timeout=8)
    payload = value.get("payload", {})
    ok = value.get("reachable") is True and payload.get("status") == "ok"
    code = "ready" if ok else value.get("error", "provider_degraded")
    access = payload.get("gpu_access", {})
    allowed = {"gpu_device_missing", "gpu_device_access_denied", "gpu_probe_tool_missing", "gpu_driver_library_mismatch",
               "gpu_nvml_unavailable", "gpu_probe_timeout", "gpu_probe_invalid_response", "gpu_probe_failed"}
    if not ok and access.get("error") in allowed:
        code = access["error"]
    print(json.dumps({"status": "ready" if ok else "not_ready", "code": code, "component": "provider"}))
    return 0 if ok else 1

if __name__ == "__main__":
    try: result = asyncio.run(main())
    except Exception:
        print(json.dumps({"status": "not_ready", "code": "diagnostic_internal_error", "component": "provider"}))
        result = 1
    raise SystemExit(result)
