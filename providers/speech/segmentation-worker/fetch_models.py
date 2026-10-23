"""Prepare only the selected VAD and CAM++; all model bytes are pinned."""
import os
from sonovect_assets import resolve
resolve("cam", os.getenv("MODELSCOPE_CACHE", "/models"), offline=False)
if os.getenv("VAD_BACKEND", "firered") == "firered":
    resolve("firered", offline=False)
else:
    resolve("fsmn", os.getenv("MODELSCOPE_CACHE", "/models"), offline=False)
print("Selected segmentation assets verified")
