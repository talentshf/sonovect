"""Read-only GPU readiness without loading models or reserving CUDA memory."""
import errno
import os
from pathlib import Path
import selectors
import subprocess
import time


def _query():
    command = ['nvidia-smi', '--query-gpu=driver_version,name,memory.total', '--format=csv,noheader,nounits']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    content = bytearray()
    deadline = time.monotonic() + 3
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired('nvidia-smi', 3)
                for key, _ in selector.select(remaining):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        content.extend(data)
                        if len(content) > 8192:
                            raise ValueError('gpu_probe_invalid_response')
            return process.wait(timeout=max(.01, deadline-time.monotonic())), bytes(content)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def gpu_health(device='cuda:0'):
    if not str(device).startswith('cuda'):
        return {'available': True, 'mode': 'cpu'}
    for path in ('/dev/nvidia0', '/dev/nvidiactl', '/dev/nvidia-uvm', '/dev/nvidia-uvm-tools'):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            os.close(descriptor)
        except OSError as error:
            code = ('gpu_device_missing' if error.errno == errno.ENOENT else
                    'gpu_device_access_denied' if error.errno in {errno.EACCES, errno.EPERM} or isinstance(error, PermissionError) else
                    'gpu_probe_failed')
            return {'available': False, 'error': code}
    try:
        code, output = _query()
        if code or not output.strip():
            return {'available': False, 'error': 'gpu_driver_library_mismatch' if b'Driver/library version mismatch' in output else 'gpu_nvml_unavailable'}
        driver, name, total = output.decode().splitlines()[0].split(',')
        identity = {'driver_version': driver.strip(), 'device': name.strip(), 'memory_total_mib': int(total)}
        try:
            version = Path('/proc/driver/nvidia/version').read_text()
            identity['kernel_flavor'] = 'open' if 'Open Kernel Module' in version else 'proprietary'
        except OSError:
            identity['kernel_flavor'] = 'unknown'
        return {'available': True, **identity}
    except FileNotFoundError:
        return {'available': False, 'error': 'gpu_probe_tool_missing'}
    except OSError:
        return {'available': False, 'error': 'gpu_probe_failed'}
    except subprocess.TimeoutExpired:
        return {'available': False, 'error': 'gpu_probe_timeout'}
    except (ValueError, UnicodeError, IndexError):
        return {'available': False, 'error': 'gpu_probe_invalid_response'}
