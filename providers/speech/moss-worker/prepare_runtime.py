"""Build an explicitly identified, inference-only MOSS compatibility package.

The upstream metadata references a missing LICENSE file. Preserve its original
statement without inventing a grant; source and changes remain in the image. Strict preimages
make upstream changes fail rather than silently applying a different patch.
"""
from pathlib import Path
import hashlib
import json
import sys
import tomllib


def replace_once(path, before, after):
    value = path.read_text()
    if value.count(before) != 1:
        raise RuntimeError("moss_compatibility_preimage_mismatch:" + path.name)
    path.write_text(value.replace(before, after))


def prepare(root):
    root = Path(root)
    preimages = {
        "pyproject.toml": "a936a262df3ee02a953922d3e9397e92d9619e0ad878bef91ea87039d1b13327",
        "src/modeling_moss_audio.py": "a52513e518c68a0ba7c636a1ab0e12f7755ceebd0ae033235dc5e2551bfcbf9c",
        "src/configuration_moss_audio.py": "e597dca441ff7fb58a5ec43186fafdfce19f31dada4955b4910059baa5d52ebd",
        "src/processing_moss_audio.py": "05fb788cbdc6482eded8d70f7d2f524bc0cdca47d001acab5661c11f02cc6fe6",
    }
    for name, expected in preimages.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("moss_upstream_hash_mismatch:" + name)
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    project = metadata["project"]
    if project["name"] != "moss-audio" or project["version"] != "0.1.0":
        raise RuntimeError("moss_upstream_version_mismatch")
    dependencies = [item for item in project["dependencies"] if item not in {"gradio", "streamlit"}]
    dependencies += ["transformers==5.20.2", "accelerate==1.15.0", "torch==2.14.1", "torchaudio==2.11.0"]
    package = '\n'.join([
        '[build-system]', 'requires = ["setuptools==84.2.0", "wheel==0.48.0"]',
        'build-backend = "setuptools.build_meta"', '', '[project]',
        'name = "moss-audio"', 'version = "0.1.0+sonovect.1"',
        'description = "MOSS-Audio inference runtime, packaged for Sonovect"',
        'requires-python = ">=3.12"', 'license = "LicenseRef-OpenMOSS-Unconfirmed"',
        'license-files = ["UPSTREAM-LICENSE-STATEMENT.md"]',
        'authors = [{name = "OpenMOSS Team"}]', 'readme = "README.md"',
        'dependencies = ' + json.dumps(dependencies), '',
        '[project.optional-dependencies]', 'demo = ["gradio", "streamlit"]', '',
        '[tool.setuptools.packages.find]', 'include = ["src", "src.*"]', '',
    ])
    replace_once(root / "src/modeling_moss_audio.py", '_tied_weights_keys: List[str] = []',
                 '_tied_weights_keys: dict[str, str] = {}')
    replace_once(root / "src/modeling_moss_audio.py", '                layer_head_mask=None,\n                output_attentions=False,\n            )[0]',
                 '            )')
    replace_once(root / "src/configuration_moss_audio.py",
                 '    def to_dict(self):\n        output = super().to_dict()',
                 '    def get_text_config(self, decoder=None, encoder=None):\n        return self.language_config\n\n    def to_dict(self):\n        output = super().to_dict()')
    replace_once(root / "src/modeling_moss_audio.py",
                 '        if cache_position is not None and cache_position[0] > 0:',
                 '        cached_length = past_key_values.get_seq_length() if hasattr(past_key_values, "get_seq_length") else 0\n        if cached_length > 0 or (cache_position is not None and cache_position[0] > 0):')
    (root / "UPSTREAM-LICENSE-STATEMENT.md").write_text(
        "# Original upstream declaration and unresolved text\n\n"
        "Pinned upstream: OpenMOSS/MOSS-Audio 5cbb1d823937cd5b5de3d8fa4d3a7253ebd3b883.\n"
        "Its original pyproject.toml points to LICENSE, but that revision has no LICENSE file.\n"
        "Its README says: Models in MOSS-Audio are licensed under the Apache License 2.0.\n"
        "This file records the declaration; it does not create or resolve a code license grant.\n"
        "Original authors: OpenMOSS Team. Sonovect modifies only the documented inference compatibility layer.\n"
        "Commercial redistribution of this derived runtime remains unconfirmed.\n")
    (root / "pyproject.toml").write_text(package)


if __name__ == "__main__":
    prepare(sys.argv[1])
