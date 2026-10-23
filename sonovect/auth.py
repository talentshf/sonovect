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
