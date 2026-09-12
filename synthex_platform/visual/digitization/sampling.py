"""Bounded, transparent sampling of traced plot pixels."""

from __future__ import annotations

import numpy as np


def sample_pixels(points: list[tuple[float, float]], strategy: str, count: int) -> list[tuple[float, float]]:
    if len(points) <= count:
        return points
    values = np.asarray(points, dtype=float)
    if strategy == "adaptive":
        # Preserve endpoints and the highest-turning-angle representatives.
        angles = np.zeros(len(values))
        vectors = np.diff(values, axis=0)
        angles[1:-1] = np.abs(np.diff(np.arctan2(vectors[:, 1], vectors[:, 0])))
        selected = np.unique(np.r_[0, np.argsort(angles)[-(count - 2):], len(values) - 1])
        return [tuple(item) for item in values[np.sort(selected)]]
    if strategy == "original_markers":
        # Marker identification is not general in V1; use a conservative bounded representative subset.
        strategy = "representative"
    indices = np.linspace(0, len(values) - 1, count, dtype=int)
    return [tuple(item) for item in values[indices]]
