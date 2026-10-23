"""Read-only GPU readiness without loading models or reserving CUDA memory."""
import os
import subprocess
from pathlib import Path


def gpu_health(device="cuda:0"):
    if not str(device).startswith("cuda"):
        return {"available": True, "mode": "cpu"}
    try:
        for path in ("/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools"):
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            os.close(descriptor)
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=3, check=False,
        )
        if result.returncode or not result.stdout.strip():
            if b"Driver/library version mismatch" in (result.stderr or b""):
                return {"available": False, "error": "gpu_driver_library_mismatch"}
            return {"available": False, "error": "gpu_nvml_unavailable"}
        row = result.stdout.decode().splitlines()[0].split(",")
        driver, name, total = row
        identity = {"driver_version": driver.strip(), "device": name.strip(), "memory_total_mib": int(total)}
        try:
            version = Path("/proc/driver/nvidia/version").read_text()
            identity["kernel_flavor"] = "open" if "Open Kernel Module" in version else "proprietary"
        except OSError:
            identity["kernel_flavor"] = "unknown"
        return {"available": True, **identity}
    except OSError:
        return {"available": False, "error": "gpu_device_access_denied"}
    except subprocess.TimeoutExpired:
        return {"available": False, "error": "gpu_probe_timeout"}
    except (ValueError, UnicodeError, IndexError):
        return {"available": False, "error": "gpu_probe_invalid_response"}
