"""Uncertainty estimates and display rounding for graph-derived estimates."""

from __future__ import annotations

import math

from .models import AxisCalibration, DigitizationUncertainty


def axis_units_per_pixel(axis: AxisCalibration) -> float:
    if axis.scale_type == "linear":
        return abs(axis.data_end - axis.data_start) / abs(axis.pixel_end - axis.pixel_start)
    # A local log scale is position-dependent; this conservative endpoint span is explicit.
    return abs(axis.data_end - axis.data_start) / abs(axis.pixel_end - axis.pixel_start)


def estimate_uncertainty(x_axis: AxisCalibration, y_axis: AxisCalibration, *, line_thickness_px: float = 1.0, marker_radius_px: float = 0.0, crop_uncertainty_px: float = 0.0, overlap_warning: bool = False) -> DigitizationUncertainty:
    pixel_error = max(1.0, x_axis.calibration_residual_px, y_axis.calibration_residual_px, line_thickness_px / 2, marker_radius_px, crop_uncertainty_px)
    contributors = ["minimum_one_pixel", "calibration_residual", "line_thickness"]
    if marker_radius_px:
        contributors.append("marker_radius")
    if crop_uncertainty_px:
        contributors.append("crop_uncertainty")
    if overlap_warning:
        contributors.append("series_overlap")
        pixel_error *= 2
    return DigitizationUncertainty(x=axis_units_per_pixel(x_axis) * pixel_error, y=axis_units_per_pixel(y_axis) * pixel_error, pixel_x=pixel_error, pixel_y=pixel_error, contributors=contributors)


def rounded_value_and_uncertainty(value: float, uncertainty: float) -> tuple[float, float]:
    if uncertainty <= 0:
        return value, uncertainty
    exponent = math.floor(math.log10(uncertainty))
    lead = uncertainty / 10 ** exponent
    # One significant uncertainty digit by default; retain a second only for 1.x.
    decimals = -exponent + (1 if lead < 2 else 0)
    return round(value, max(0, decimals)), round(uncertainty, max(0, decimals))
