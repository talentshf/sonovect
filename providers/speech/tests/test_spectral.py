"""Run with the existing segmentation image's NumPy/SciPy runtime."""
import sys
from pathlib import Path
import unittest
import numpy as np
from scipy.linalg import eigh
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'segmentation-worker'))
from spectral import spectral_embeddings


class SpectralTest(unittest.TestCase):
    def test_same_selected_subspace_and_speaker_count(self):
        rng = np.random.default_rng(17)
        for count in (20, 80, 200):
            affinity = rng.random((count, count))
            affinity = (affinity + affinity.T) / 2
            groups = np.arange(count) // max(1, count // 3)
            affinity += (groups[:, None] == groups[None, :]) * 4
            laplacian = np.diag(affinity.sum(axis=1)) - affinity
            values, original = eigh(laplacian)
            expected = int(np.argmax(np.diff(values[:16]))) + 1
            for oracle in (None, 3):
                output, speakers = spectral_embeddings(laplacian, oracle=oracle)
                self.assertEqual(speakers, oracle or expected)
                np.testing.assert_allclose(output @ output.T, original[:, :speakers] @ original[:, :speakers].T, atol=1e-7)


if __name__ == '__main__':
    unittest.main()
