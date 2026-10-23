"""Compute only the spectral subspace consumed by FunASR's speaker selection."""
from __future__ import annotations
import numpy as np
from scipy.linalg import eigh


def spectral_embeddings(laplacian, minimum=1, maximum=15, oracle=None):
    count = laplacian.shape[0]
    if not count:
        return np.empty((0, 0)), 0
    upper = min(count - 1, max(maximum, int(oracle or 1) - 1))
    values, vectors = eigh(laplacian, subset_by_index=(0, upper), driver='evr')
    if oracle is not None:
        speakers = min(count, int(oracle))
    else:
        gaps = np.diff(values[minimum - 1:maximum + 1])
        speakers = int(np.argmax(gaps)) + minimum if gaps.size else 1
    return vectors[:, :speakers], speakers
