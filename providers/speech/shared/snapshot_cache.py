from __future__ import annotations

import logging
import os
from collections.abc import Callable


def resolve_pinned_snapshot(
    download: Callable[..., str],
    *,
    repo_id: str,
    revision: str,
    logger: logging.Logger,
) -> str:
    """Resolve an immutable model revision from cache before using the network."""
    try:
        from sonovect_assets import catalog, verify_identity
    except ModuleNotFoundError:
        from sonovect.assets import catalog, verify_identity
    matches = [m for m in catalog().values() if m["repo_id"] == repo_id and m["revision"] == revision]
    if len(matches) != 1:
        raise RuntimeError("model_identity_not_in_catalog")
    offline = os.getenv("SONOVECT_MODELS_OFFLINE", "1").lower() in {"1", "true", "yes"}
    path = download(repo_id=repo_id, revision=revision, local_files_only=offline,
                    allow_patterns=list(matches[0]["files"]))
    verify_identity(path, repo_id, revision)
    logger.info("Verified pinned model snapshot %s@%s", repo_id, revision)
    return path
