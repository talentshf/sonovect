"""Explicit credential configuration, shared by server and clients."""
from pathlib import Path
import os


def token_from_env() -> str:
    token = os.getenv("SONOVECT_TOKEN", "").strip()
    filename = os.getenv("SONOVECT_TOKEN_FILE", "").strip()
    if token and filename:
        raise ValueError("Set SONOVECT_TOKEN or SONOVECT_TOKEN_FILE, not both")
    if filename:
        try:
            token = Path(filename).expanduser().read_text().strip()
        except OSError:
            raise ValueError("The configured token file is not readable") from None
    return token


def provider_headers(settings):
    """Optional upstream secret stays in an operator-managed file, never a URL."""
    if settings.provider_token_file is None:
        return {}
    try:
        with settings.provider_token_file.open("rb") as f:
            raw = f.read(4097)
        token = raw.decode().strip()
        if len(raw) > 4096 or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("invalid_provider_token")
    except (OSError, UnicodeError, ValueError):
        raise RuntimeError("provider_token_unavailable") from None
    return {"Authorization": "Bearer " + token}
