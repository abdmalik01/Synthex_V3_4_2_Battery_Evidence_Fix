"""Small deterministic color masks using NumPy/Pillow, intentionally not a CV framework."""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from .models import PlotArea


def crop_plot(image_png: bytes, area: PlotArea) -> np.ndarray:
    image = Image.open(BytesIO(image_png)).convert("RGB")
    image_array = np.asarray(image)
    box = area.bbox
    x0, y0, x1, y1 = (round(box.x0), round(box.y0), round(box.x1), round(box.y1))
    if x0 < 0 or y0 < 0 or x1 > image_array.shape[1] or y1 > image_array.shape[0] or x1 - x0 < 16 or y1 - y0 < 16:
        raise ValueError("Plot area is outside the rendered image or too small.")
    return image_array[y0:y1, x0:x1]


def color_mask(plot: np.ndarray, color: tuple[int, int, int], tolerance: float = 60.0) -> np.ndarray:
    """Return pixels close to a selected RGB color, excluding near-white background."""
    distance = np.sqrt(np.sum((plot.astype(float) - np.asarray(color, dtype=float)) ** 2, axis=2))
    foreground = np.min(plot, axis=2) < 245
    return (distance <= tolerance) & foreground


def candidate_colors(plot: np.ndarray, max_colors: int = 8) -> list[tuple[int, int, int]]:
    """Find saturated, non-gray representative colors. Labels are deliberately not inferred."""
    flat = plot.reshape(-1, 3)
    spread = flat.max(axis=1).astype(int) - flat.min(axis=1).astype(int)
    candidates = flat[(spread > 45) & (flat.min(axis=1) < 220)]
    if not len(candidates):
        return []
    quantized = (candidates // 32) * 32
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    ordered = colors[np.argsort(counts)[::-1]]
    return [tuple(map(int, color)) for color in ordered[:max_colors]]


def trace_y_by_x(mask: np.ndarray, minimum_columns: int = 8) -> list[tuple[float, float]]:
    """One robust median y per populated x column; preserves no fake sub-pixel precision."""
    points: list[tuple[float, float]] = []
    for x in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, x])
        if ys.size:
            points.append((float(x), float(np.median(ys))))
    return points if len(points) >= minimum_columns else []
