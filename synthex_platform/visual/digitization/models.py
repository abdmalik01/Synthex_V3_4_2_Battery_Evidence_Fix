"""Typed, auditable models for estimated values recovered from plot pixels."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

CalibrationState = Literal["verified", "user_confirmed", "automatically_inferred", "ambiguous", "failed"]
DigitizationStatus = Literal["completed", "rejected", "diagnostic"]
SamplingStrategy = Literal["original_markers", "fixed_x_intervals", "adaptive", "representative"]


class PixelBoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("Pixel bounding box must have positive area.")
        return self


class PlotArea(BaseModel):
    """Pixel-space rectangle inside a rendered figure or panel image."""

    bbox: PixelBoundingBox
    coordinate_space: Literal["rendered_figure_pixels", "rendered_panel_pixels"] = "rendered_figure_pixels"
    state: CalibrationState = "user_confirmed"
    resolution_width: int = Field(gt=0)
    resolution_height: int = Field(gt=0)


class AxisCalibration(BaseModel):
    axis: Literal["x", "y"]
    pixel_start: float
    pixel_end: float
    data_start: float
    data_end: float
    scale_type: Literal["linear", "log10"] = "linear"
    state: CalibrationState = "user_confirmed"
    tick_evidence: list[str] = Field(default_factory=list)
    calibration_residual_px: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _valid_calibration(self):
        if self.pixel_start == self.pixel_end:
            raise ValueError("Axis calibration needs two distinct pixel positions.")
        if self.data_start == self.data_end:
            raise ValueError("Axis calibration needs two distinct data values.")
        if self.scale_type == "log10" and (self.data_start <= 0 or self.data_end <= 0):
            raise ValueError("Log10 axis calibration values must be positive.")
        return self


class SeriesSelection(BaseModel):
    """A user-selected or deterministic color target; no inferred labels are required."""

    series_id: str = Field(pattern=r"^series-")
    color_rgb: tuple[int, int, int] | None = None
    series_label: str | None = None
    association_status: Literal["verified", "inferred", "ambiguous"] = "ambiguous"

    @model_validator(mode="after")
    def _channels(self):
        if self.color_rgb and any(channel < 0 or channel > 255 for channel in self.color_rgb):
            raise ValueError("RGB channels must be between 0 and 255.")
        return self


class DigitizationRequest(BaseModel):
    source_id: str
    page: int = Field(ge=1)
    figure_id: str = Field(pattern=r"^fig-")
    panel: str | None = None
    plot_area: PlotArea
    x_axis: AxisCalibration
    y_axis: AxisCalibration
    series: list[SeriesSelection] = Field(default_factory=list)
    sampling_strategy: SamplingStrategy = "representative"
    sample_count: int = Field(default=100, ge=2, le=500)
    diagnostic_mode: bool = False
    requested_geometry: Literal["cartesian_2d", "dual_y", "broken_axis", "polar", "ternary", "three_d", "heatmap", "contour", "image", "schematic"] = "cartesian_2d"
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _matching_axes(self):
        if self.x_axis.axis != "x" or self.y_axis.axis != "y":
            raise ValueError("DigitizationRequest requires x and y calibration in their matching fields.")
        return self


class DigitizationUncertainty(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    pixel_x: float = Field(ge=0)
    pixel_y: float = Field(ge=0)
    contributors: list[str] = Field(default_factory=list)


class DigitizedPoint(BaseModel):
    x: float
    y: float
    raw_pixel_x: float
    raw_pixel_y: float
    figure_id: str = Field(pattern=r"^fig-")
    panel: str | None = None
    series_id: str = Field(pattern=r"^series-")
    estimated: Literal[True] = True
    origin: Literal["figure_digitized"] = "figure_digitized"
    evidence_strength: Literal["estimated_digitized"] = "estimated_digitized"
    admission_status: Literal["not_submitted"] = "not_submitted"
    digitization_method: str
    digitizer_version: str
    uncertainty_x: float = Field(ge=0)
    uncertainty_y: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    quality_status: Literal["accepted", "warning"] = "accepted"


class DigitizedSeries(BaseModel):
    series_id: str = Field(pattern=r"^series-")
    series_label: str | None = None
    color_rgb: tuple[int, int, int] | None = None
    association_status: Literal["verified", "inferred", "ambiguous"] = "ambiguous"
    points: list[DigitizedPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DigitizationResult(BaseModel):
    digitization_id: str = Field(pattern=r"^dig-")
    source_id: str
    page: int = Field(ge=1)
    figure_id: str = Field(pattern=r"^fig-")
    panel: str | None = None
    plot_area: PlotArea
    source_image_checksum: str
    calibration: dict[str, AxisCalibration]
    series: list[DigitizedSeries] = Field(default_factory=list)
    uncertainty: DigitizationUncertainty | None = None
    algorithm: str = "numpy_pillow_colored_curve_v1"
    digitizer_version: str = "digitization_v1"
    status: DigitizationStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any]
