"""Check response semantics, including degraded HTTP-200 responses."""
import json
import sys
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:" + sys.argv[1] + "/health", timeout=8) as response:
        ok = json.load(response).get("status") == "ok"
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
