"""Generate reviewed JSON Schema and OpenAPI documents without loading models."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sonovect.api import create_app
from sonovect.capabilities import describe
from sonovect.config import Settings
from sonovect.models import Analysis, Options, Transcript


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        app = create_app(Settings(data_dir=Path(temporary), token="schema-generation-only"))
        values = {"openapi-v1.json": app.openapi(), "job-options.schema.json": Options.model_json_schema(),
                  "capabilities.example.json": describe(app.state.settings)}
    for name, model in (("funasr-result", Transcript), ("audio-analysis", Analysis)):
        schema = model.model_json_schema()
        values[name + ".schema.json"] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": name, "type": "array", "items": {k: v for k, v in schema.items() if k != "$defs"},
            "$defs": schema.get("$defs", {})}
    for name, value in values.items():
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "contracts")
