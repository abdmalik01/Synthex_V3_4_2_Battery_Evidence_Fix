"""Typed, renderer-neutral analytic objects derived from canonical archives."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyticMeasurementRow(BaseModel):
    archive_id: str
    source_id: str | None = None
    material_id: str | None = None
    process_id: str | None = None
    device_id: str | None = None
    experiment_id: str | None = None
    calculation_id: str | None = None
    modality: Literal["experimental", "computational", "process"]
    property_name: str
    raw_property_name: str | None = None
    value: float | None = None
    raw_value: str | None = None
    unit: str | None = None
    normalized_unit: str | None = None
    qualifier: str = "unknown"
    material_label: str | None = None
    method: str | None = None
    record_type: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    visual_evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    provenance_origins: list[str] = Field(default_factory=list)


class AnalyticQuery(BaseModel):
    property_name: str | None = None
    material_id: str | None = None
    material_contains: str | None = None
    method_contains: str | None = None
    source_id: str | None = None
    experiment_type: str | None = None
    calculation_type: str | None = None
    temperature_min: float | None = None
    temperature_max: float | None = None
    cycle_min: float | None = None
    cycle_max: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    provenance_origin: str | None = None
    modalities: set[Literal["experimental", "computational", "process"]] | None = None
    include_noncanonical: bool = False


class VisualizationSpec(BaseModel):
    visualization_id: str = Field(pattern=r"^viz-")
    chart_type: Literal["bar", "line", "scatter", "heatmap", "contour", "radar"]
    title: str
    subtitle: str | None = None
    x_field: str | None = None
    y_field: str | None = None
    z_field: str | None = None
    value_field: str = "value"
    series_field: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    z_label: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    source_count: int = 0
    record_count: int = 0
    provenance_references: list[dict[str, Any]] = Field(default_factory=list)
    rendering_warnings: list[str] = Field(default_factory=list)
    eligible: bool = False
    reason: str | None = None
    radar_fields: list[str] = Field(default_factory=list)
    radar_normalization_policy: str | None = None