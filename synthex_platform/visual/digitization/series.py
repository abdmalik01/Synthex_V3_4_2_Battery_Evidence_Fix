"""Color-selected series extraction and pixel coordinate conversion."""

from __future__ import annotations

from .calibration import pixel_to_data
from .image_processing import color_mask, trace_y_by_x
from .models import AxisCalibration, SeriesSelection
from .sampling import sample_pixels


def extract_selected_series(plot, selection: SeriesSelection, x_axis: AxisCalibration, y_axis: AxisCalibration, *, pixel_origin: tuple[float, float], strategy: str, sample_count: int, tolerance: float = 60.0) -> list[tuple[float, float, float, float]]:
    if selection.color_rgb is None:
        return []
    pixels = trace_y_by_x(color_mask(plot, selection.color_rgb, tolerance))
    sampled = sample_pixels(pixels, strategy, sample_count)
    origin_x, origin_y = pixel_origin
    return [(pixel_to_data(origin_x + x, x_axis), pixel_to_data(origin_y + y, y_axis), origin_x + x, origin_y + y) for x, y in sampled]
