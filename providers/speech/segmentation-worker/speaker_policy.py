from __future__ import annotations


def should_apply_low_cohesion_fallback(
    *,
    window_count: int,
    raw_cluster_count: int,
    cohesion_median: float | None,
    minimum_windows: int,
    maximum_cohesion: float,
) -> bool:
    return (
        raw_cluster_count == 1
        and window_count >= minimum_windows
        and cohesion_median is not None
        and cohesion_median < maximum_cohesion
    )
