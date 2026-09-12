"""Deterministic pixel-to-data transforms; no guessed scientific bounds."""

from __future__ import annotations

import math

from .models import AxisCalibration


def calibration_is_production_ready(axis: AxisCalibration) -> bool:
    return axis.state in {"verified", "user_confirmed"}


def pixel_to_data(pixel: float, calibration: AxisCalibration) -> float:
    fraction = (pixel - calibration.pixel_start) / (calibration.pixel_end - calibration.pixel_start)
    if calibration.scale_type == "linear":
        return calibration.data_start + fraction * (calibration.data_end - calibration.data_start)
    log_value = math.log10(calibration.data_start) + fraction * (
        math.log10(calibration.data_end) - math.log10(calibration.data_start)
    )
    return 10 ** log_value


def data_to_pixel(value: float, calibration: AxisCalibration) -> float:
    if calibration.scale_type == "linear":
        fraction = (value - calibration.data_start) / (calibration.data_end - calibration.data_start)
    else:
        if value <= 0:
            raise ValueError("Log10 coordinates must be positive.")
        fraction = (math.log10(value) - math.log10(calibration.data_start)) / (
            math.log10(calibration.data_end) - math.log10(calibration.data_start)
        )
    return calibration.pixel_start + fraction * (calibration.pixel_end - calibration.pixel_start)
