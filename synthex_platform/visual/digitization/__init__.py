"""Calibrated, sidecar-only digitization of supported 2D scientific plots."""

from .models import (
    AxisCalibration, DigitizationRequest, DigitizationResult, DigitizedPoint,
    DigitizedSeries, DigitizationUncertainty, PlotArea, SeriesSelection,
)
from .pipeline import digitize_plot

__all__ = [
    "AxisCalibration", "DigitizationRequest", "DigitizationResult", "DigitizedPoint",
    "DigitizedSeries", "DigitizationUncertainty", "PlotArea", "SeriesSelection", "digitize_plot",
]
