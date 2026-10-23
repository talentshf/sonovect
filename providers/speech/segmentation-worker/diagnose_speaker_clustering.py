from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import scipy.linalg
import torch
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score

from app import SAMPLE_RATE, Models
from funasr.models.campplus.utils import sv_chunk


DEFAULT_THRESHOLDS = (0.78, 0.82, 0.86, 0.90, 0.92, 0.94, 0.96, 0.98)


def _cluster_count(labels: np.ndarray) -> int:
    return int(labels.max()) + 1 if labels.size else 0


def diagnose(
    path: Path,
    thresholds: tuple[float, ...],
    references: tuple[tuple[str, Path], ...] = (),
) -> dict[str, Any]:
    models = Models()
    models.load()
    waveform, _ = librosa.load(path, sr=SAMPLE_RATE, mono=True)
    duration_ms = round(len(waveform) * 1000 / SAMPLE_RATE)
    speech_regions = models.speech_regions(waveform)
    segments = sv_chunk(
        [
            [
                float(region["start_ms"]) / 1000,
                float(region["end_ms"]) / 1000,
                waveform[
                    round(int(region["start_ms"]) * SAMPLE_RATE / 1000) :
                    round(int(region["end_ms"]) * SAMPLE_RATE / 1000)
                ],
            ]
            for region in speech_regions
        ],
        fs=SAMPLE_RATE,
    )
    if len(segments) < 2:
        return {"status": "insufficient_speech_windows", "audio": {"duration_ms": duration_ms},
                "speech_region_count": len(speech_regions), "window_count": len(segments),
                "oracle_speaker_counts": [], "agglomerative": []}
    matrix = np.stack(
        [models._embedding(waveform, round(item[0] * 1000), round(item[1] * 1000)) for item in segments]
    )
    if not np.isfinite(matrix).all() or np.any(np.linalg.norm(matrix, axis=1) == 0):
        return {"status": "invalid_speaker_embeddings", "audio": {"duration_ms": duration_ms},
                "speech_region_count": len(speech_regions), "window_count": len(segments),
                "oracle_speaker_counts": [], "agglomerative": []}
    raw_labels = np.asarray(models._cluster.spectral_cluster(matrix), dtype=int)

    normalized_windows = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    window_affinity = normalized_windows @ normalized_windows.T
    window_pairwise = window_affinity[np.triu_indices_from(window_affinity, k=1)]
    spectral = models._cluster.spectral_cluster
    pruned = spectral.p_pruning(spectral.get_sim_mat(matrix).copy())
    laplacian = spectral.get_laplacian(0.5 * (pruned + pruned.T))
    eigenvalues = scipy.linalg.eigh(laplacian, eigvals_only=True)[:16]
    eigen_gaps = np.diff(eigenvalues)

    raw_centers = np.stack([matrix[raw_labels == label].mean(0) for label in range(_cluster_count(raw_labels))])
    normalized = raw_centers / np.linalg.norm(raw_centers, axis=1, keepdims=True)
    affinity = normalized @ normalized.T
    pairwise = affinity[np.triu_indices_from(affinity, k=1)]

    thresholds_report: list[dict[str, Any]] = []
    for threshold in thresholds:
        labels = models._cluster.merge_by_cos(raw_labels.copy(), matrix, threshold)
        thresholds_report.append({"merge_threshold": threshold, "cluster_count": _cluster_count(labels)})

    oracle_report: list[dict[str, Any]] = []
    for speaker_count in range(2, min(8, len(segments) - 1) + 1):
        labels = np.asarray(models._cluster.spectral_cluster(matrix, speaker_count), dtype=int)
        counts = np.bincount(labels, minlength=speaker_count)
        merged_labels = models._cluster.merge_by_cos(labels.copy(), matrix, 0.78)
        oracle_report.append(
            {
                "speaker_count": speaker_count,
                "cluster_count_after_default_merge": _cluster_count(merged_labels),
                "silhouette_cosine": round(float(silhouette_score(matrix, labels, metric="cosine")), 6)
                if 1 < len(set(labels)) < len(matrix) else None,
                "minimum_windows_per_cluster": int(counts.min()),
                "maximum_windows_per_cluster": int(counts.max()),
            }
        )

    agglomerative_report: list[dict[str, Any]] = []
    for distance_threshold in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70):
        labels = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=distance_threshold,
        ).fit_predict(matrix)
        counts = np.bincount(labels)
        agglomerative_report.append(
            {
                "distance_threshold": distance_threshold,
                "cluster_count": int(len(counts)),
                "minimum_windows_per_cluster": int(counts.min()),
                "maximum_windows_per_cluster": int(counts.max()),
            }
        )

    reference_vectors: list[tuple[str, np.ndarray]] = []
    for label, reference_path in references:
        reference_waveform, _ = librosa.load(reference_path, sr=SAMPLE_RATE, mono=True)
        reference_vectors.append(
            (label, models._embedding(reference_waveform, 0, round(len(reference_waveform) * 1000 / SAMPLE_RATE)))
        )
    reference_cosine = [
        {
            "left": left_label,
            "right": right_label,
            "cosine": round(float(left_vector @ right_vector), 6),
        }
        for left_index, (left_label, left_vector) in enumerate(reference_vectors)
        for right_label, right_vector in reference_vectors[left_index + 1 :]
    ]

    return {
        "status": "completed",
        "audio": {"duration_ms": duration_ms},
        "speech_region_count": len(speech_regions),
        "window_count": len(segments),
        "spectral_cluster_count": _cluster_count(raw_labels),
        "spectral_eigenvalues": [round(float(value), 6) for value in eigenvalues.tolist()],
        "spectral_eigen_gaps": [round(float(value), 6) for value in eigen_gaps.tolist()],
        "window_cosine": {
            "count": int(window_pairwise.size),
            "minimum": round(float(window_pairwise.min()), 6) if window_pairwise.size else None,
            "p10": round(float(np.percentile(window_pairwise, 10)), 6) if window_pairwise.size else None,
            "median": round(float(np.median(window_pairwise)), 6) if window_pairwise.size else None,
            "p90": round(float(np.percentile(window_pairwise, 90)), 6) if window_pairwise.size else None,
            "maximum": round(float(window_pairwise.max()), 6) if window_pairwise.size else None,
        },
        "spectral_center_cosine": {
            "count": int(pairwise.size),
            "minimum": round(float(pairwise.min()), 6) if pairwise.size else None,
            "median": round(float(np.median(pairwise)), 6) if pairwise.size else None,
            "p90": round(float(np.percentile(pairwise, 90)), 6) if pairwise.size else None,
            "maximum": round(float(pairwise.max()), 6) if pairwise.size else None,
        },
        "thresholds": thresholds_report,
        "oracle_speaker_counts": oracle_report,
        "agglomerative": agglomerative_report,
        "reference_cosine": reference_cosine,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report speaker clustering sensitivity without transcript content.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--threshold", action="append", type=float, dest="thresholds")
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Optional known-speaker reference used only for cosine calibration.",
    )
    args = parser.parse_args()
    thresholds = tuple(args.thresholds) if args.thresholds else DEFAULT_THRESHOLDS
    references = tuple((value.split("=", 1)[0], Path(value.split("=", 1)[1])) for value in args.reference)
    report = diagnose(args.audio, thresholds, references)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
