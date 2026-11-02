"""Load audited local VAD/embedding bytes, without following a mutable hub head."""
import hashlib
import json
from pathlib import Path


MODEL_REVISIONS = {'fsmn-vad': 'v2.0.4', 'cam++': 'v2.0.2'}


def pinned_revision(alias):
    if alias not in MODEL_REVISIONS:
        raise ValueError('segmentation_model_not_pinned')
    return MODEL_REVISIONS[alias]


def resolve_pinned_model(alias, cache_root, manifest_path=None):
    manifest = json.loads(Path(manifest_path or Path(__file__).with_name('pinned-models.json')).read_text())
    model = manifest['aliases'].get(alias)
    if model is None:
        raise ValueError('segmentation_model_not_pinned')
    # Ask the SDK for its actual cache location. Keep the SDK cache layout only
    # when it exists, and subject both layouts to the same byte verification.
    root = Path(cache_root) / 'models' / 'iic' / model
    if not root.is_dir():
        from modelscope import snapshot_download
        root = Path(snapshot_download('iic/' + model, revision=pinned_revision(alias),
                                     cache_dir=str(cache_root), local_files_only=True))
    for name, expected in manifest['models'][model].items():
        path = root / name
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise RuntimeError('segmentation_model_hash_mismatch:' + alias + ':' + name)
    return str(root)
