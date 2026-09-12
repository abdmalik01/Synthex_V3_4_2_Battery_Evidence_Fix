"""Renderer-neutral specifications and conservative scientific eligibility checks."""

from __future__ import annotations

from typing import Any

from synthex_platform.core.identifiers import stable_id
from .models import AnalyticMeasurementRow, AnalyticQuery, VisualizationSpec


def field_value(row: AnalyticMeasurementRow, field: str | None):
    if not field:
        return None
    if field.startswith("conditions."):
        return row.conditions.get(field.removeprefix("conditions."))
    return getattr(row, field, None)


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _units(rows: list[AnalyticMeasurementRow], field: str) -> set[str]:
    if field != "value":
        return set()
    return {row.normalized_unit or row.unit for row in rows if row.value is not None and (row.normalized_unit or row.unit)}


def _eligibility(chart_type: str, rows: list[AnalyticMeasurementRow], x_field: str | None, y_field: str | None, radar_fields: list[str], radar_policy: str | None):
    if not rows:
        return False, "no_records"
    if chart_type == "radar":
        if radar_policy != "minmax_per_metric":
            return False, "radar_requires_explicit_normalization_policy"
        if len(radar_fields) < 3 or len(rows) < 2 or not all(any(_numeric(field_value(row, field)) for row in rows) for field in radar_fields):
            return False, "invalid_radar_dimensions"
        return True, None
    if not x_field or not y_field:
        return False, "missing_axes"
    usable = [row for row in rows if _numeric(field_value(row, x_field)) and _numeric(field_value(row, y_field))]
    if chart_type == "bar":
        usable = [row for row in rows if field_value(row, x_field) is not None and _numeric(field_value(row, y_field))]
    if not usable:
        return False, "missing_numeric_axes"
    units = _units(usable, y_field)
    if len(units) > 1:
        return False, "incompatible_y_units"
    if chart_type == "contour":
        xs, ys = {field_value(row, x_field) for row in usable}, {field_value(row, y_field) for row in usable}
        if len(usable) < 4 or len(xs) < 2 or len(ys) < 2:
            return False, "insufficient_data_density"
    return True, None


def build_visualization_spec(
    rows: list[AnalyticMeasurementRow], chart_type: str, title: str, *, x_field: str | None = None,
    y_field: str | None = "value", series_field: str | None = None, subtitle: str | None = None,
    query: AnalyticQuery | None = None, radar_fields: list[str] | None = None,
    radar_normalization_policy: str | None = None,
) -> VisualizationSpec:
    radar_fields = radar_fields or []
    eligible, reason = _eligibility(chart_type, rows, x_field, y_field, radar_fields, radar_normalization_policy)
    record_ids = [(row.archive_id, row.experiment_id, row.calculation_id, row.property_name) for row in rows]
    visualization_id = stable_id("viz", query.model_dump() if query else {}, chart_type, x_field, y_field, series_field, record_ids)
    references = [{"archive_id": row.archive_id, "source_id": row.source_id, "experiment_id": row.experiment_id,
                   "calculation_id": row.calculation_id, "evidence": row.evidence_references} for row in rows]
    units = {"y": next(iter(_units(rows, y_field or "value")), "")}
    return VisualizationSpec(
        visualization_id=visualization_id, chart_type=chart_type, title=title, subtitle=subtitle,
        x_field=x_field, y_field=y_field, series_field=series_field, x_label=x_field, y_label=y_field,
        units={key: value for key, value in units.items() if value}, filters_applied=query.model_dump(exclude_none=True) if query else {},
        source_count=len({row.source_id for row in rows if row.source_id}), record_count=len(rows),
        provenance_references=references, eligible=eligible, reason=reason, radar_fields=radar_fields,
        radar_normalization_policy=radar_normalization_policy,
    )
