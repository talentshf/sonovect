"""Bounded HTTPS input materialization with pinned, public network targets."""
import hashlib
import http.client
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import ssl
import time
from urllib.parse import urlsplit

from .media import MediaError


def input_url(value, hosts):
    try:
        p = urlsplit(value)
        if (not isinstance(value, str) or len(value) > 16384 or any(c.isspace() for c in value)
                or p.scheme != "https" or p.port not in (None, 443) or p.username or p.password
                or p.fragment or not p.hostname or p.hostname.lower() not in hosts):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise MediaError("input_url_not_allowed") from None
    return p


def download_source(settings, source):
    """Never follow redirects or pass a service token to an input host."""
    p = input_url(source["remote_url"], settings.compat_input_hosts)
    target = Path(source["path"])
    if target.exists():
        with target.open("rb") as existing:
            digest = hashlib.file_digest(existing, "sha256").hexdigest()
        if source.get("sha256") and source["sha256"] != digest:
            raise MediaError("input_integrity_failed")
        return {**source, "sha256": digest, "size": target.stat().st_size}
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise MediaError("input_target_not_allowed")
        if shutil.disk_usage(target.parent).free < settings.max_upload_bytes + 16 * 1024**2:
            raise MediaError("input_storage_unavailable")
        deadline = time.monotonic() + settings.compat_download_timeout
        connection = http.client.HTTPSConnection(p.hostname, timeout=min(30, settings.compat_download_timeout),
                                                  context=ssl.create_default_context())
        address = sorted(addresses)[0]
        connection._create_connection = lambda ignored, timeout, source_address=None: socket.create_connection(
            (address, 443), timeout=timeout, source_address=source_address)
        temporary = target.with_suffix(".download")
        # A previous interrupted download has never been admitted as input.
        temporary.unlink(missing_ok=True)
        try:
            connection.request("GET", (p.path or "/") + ("?" + p.query if p.query else ""),
                               headers={"Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status != 200:
                raise MediaError("input_download_failed")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > settings.max_upload_bytes):
                raise MediaError("input_limit_exceeded")
            size, digest = 0, hashlib.sha256()
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                while not response.isclosed():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MediaError("input_download_timeout")
                    sock = getattr(getattr(response.fp, "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(min(30, remaining))
                    # One socket read per iteration preserves the total deadline
                    # even when the server continuously trickles small chunks.
                    chunk = response.read1(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise MediaError("input_limit_exceeded")
                    output.write(chunk); digest.update(chunk)
                output.flush(); os.fsync(output.fileno())
            if not size or length is not None and size != int(length):
                raise MediaError("input_download_failed")
            checksum = digest.hexdigest()
            if source.get("sha256") and source["sha256"] != checksum:
                raise MediaError("input_integrity_failed")
            os.replace(temporary, target)
            return {**source, "sha256": checksum, "size": size}
        finally:
            connection.close()
            temporary.unlink(missing_ok=True)
    except MediaError:
        raise
    except (TimeoutError, socket.timeout):
        raise MediaError("input_download_timeout") from None
    except (OSError, ValueError, http.client.HTTPException):
        raise MediaError("input_download_failed") from None
