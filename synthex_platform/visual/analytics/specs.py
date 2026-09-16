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


def _condition_keys(rows: list[AnalyticMeasurementRow]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        keys.update(
            key for key in row.conditions
            if not key.endswith("_unit") and not key.endswith("_raw")
        )
    return keys


def _units(rows: list[AnalyticMeasurementRow], field: str | None) -> set[str]:
    if not field:
        return set()
    if field == "value":
        return {
            row.normalized_unit or row.unit
            for row in rows
            if row.value is not None and (row.normalized_unit or row.unit)
        }
    if field.startswith("conditions."):
        key = field.removeprefix("conditions.")
        return {
            str(row.conditions[f"{key}_unit"])
            for row in rows
            if row.conditions.get(f"{key}_unit") not in (None, "")
        }
    return set()


def numeric_fields(rows: list[AnalyticMeasurementRow]) -> list[str]:
    """Return numeric plot dimensions actually present in the selected rows."""
    fields: list[str] = []
    if any(_numeric(row.value) for row in rows):
        fields.append("value")
    for key in sorted(_condition_keys(rows), key=str.casefold):
        field = f"conditions.{key}"
        if any(_numeric(field_value(row, field)) for row in rows):
            fields.append(field)
    return fields


def categorical_fields(rows: list[AnalyticMeasurementRow]) -> list[str]:
    """Return useful grouping/category fields without exposing internal IDs as axes."""
    fields: list[str] = []
    for field in ("material_label", "record_type", "method"):
        values = [field_value(row, field) for row in rows]
        if any(value not in (None, "") for value in values):
            fields.append(field)
    for key in sorted(_condition_keys(rows), key=str.casefold):
        field = f"conditions.{key}"
        values = [field_value(row, field) for row in rows]
        if any(isinstance(value, str) and value.strip() for value in values):
            fields.append(field)
    return fields


def numeric_dimension_summary(rows: list[AnalyticMeasurementRow]) -> list[dict[str, Any]]:
    """Summarize numeric coverage without creating or interpolating observations."""
    summary: list[dict[str, Any]] = []
    for field in numeric_fields(rows):
        values = [field_value(row, field) for row in rows]
        numeric_values = [value for value in values if _numeric(value)]
        units = sorted(_units(rows, field), key=str.casefold)
        summary.append({
            "field": field,
            "observations": len(numeric_values),
            "unique_values": len(set(numeric_values)),
            "missing": len(rows) - len(numeric_values),
            "units": " | ".join(units),
        })
    return summary


def surface_coverage(
    rows: list[AnalyticMeasurementRow],
    x_field: str | None,
    y_field: str | None,
    z_field: str | None,
) -> dict[str, Any]:
    """Describe joint XYZ coverage used by heatmap/contour eligibility."""
    if not x_field or not y_field or not z_field:
        return {
            "records": len(rows),
            "joint_xy": 0,
            "joint_xyz": 0,
            "unique_x": 0,
            "unique_y": 0,
            "unique_coordinates": 0,
        }
    xy_rows = [
        row for row in rows
        if _numeric(field_value(row, x_field)) and _numeric(field_value(row, y_field))
    ]
    xyz_rows = [
        row for row in xy_rows
        if _numeric(field_value(row, z_field))
    ]
    xs = {field_value(row, x_field) for row in xyz_rows}
    ys = {field_value(row, y_field) for row in xyz_rows}
    coordinates = {
        (field_value(row, x_field), field_value(row, y_field))
        for row in xyz_rows
    }
    return {
        "records": len(rows),
        "joint_xy": len(xy_rows),
        "joint_xyz": len(xyz_rows),
        "unique_x": len(xs),
        "unique_y": len(ys),
        "unique_coordinates": len(coordinates),
        "x_units": " | ".join(sorted(_units(xyz_rows, x_field), key=str.casefold)),
        "y_units": " | ".join(sorted(_units(xyz_rows, y_field), key=str.casefold)),
        "z_units": " | ".join(sorted(_units(xyz_rows, z_field), key=str.casefold)),
    }


def chart_field_options(rows: list[AnalyticMeasurementRow], chart_type: str) -> dict[str, list[str]]:
    """Expose only field roles that are scientifically/rendering-compatible with a chart."""
    numeric = numeric_fields(rows)
    numeric_conditions = [field for field in numeric if field != "value"]
    categorical = categorical_fields(rows)
    if chart_type == "bar":
        return {
            "x": list(dict.fromkeys(categorical + numeric_conditions)),
            "y": numeric,
            "z": [],
            "series": categorical,
        }
    if chart_type in {"line", "scatter"}:
        return {
            "x": numeric_conditions,
            "y": numeric,
            "z": [],
            "series": categorical,
        }
    if chart_type in {"heatmap", "contour"}:
        return {
            "x": numeric_conditions,
            "y": numeric_conditions,
            "z": numeric,
            "series": categorical,
        }
    return {"x": numeric_conditions, "y": numeric, "z": [], "series": categorical}


def _eligible_rows(
    rows: list[AnalyticMeasurementRow],
    x_field: str,
    y_field: str,
    z_field: str | None = None,
    *,
    categorical_x: bool = False,
) -> list[AnalyticMeasurementRow]:
    return [
        row for row in rows
        if (field_value(row, x_field) is not None if categorical_x else _numeric(field_value(row, x_field)))
        and _numeric(field_value(row, y_field))
        and (z_field is None or _numeric(field_value(row, z_field)))
    ]


def _eligibility(
    chart_type: str,
    rows: list[AnalyticMeasurementRow],
    x_field: str | None,
    y_field: str | None,
    z_field: str | None,
    radar_fields: list[str],
    radar_policy: str | None,
):
    if not rows:
        return False, "no_records"
    if chart_type == "radar":
        if radar_policy != "minmax_per_metric":
            return False, "radar_requires_explicit_normalization_policy"
        if len(radar_fields) < 3 or len(rows) < 2 or not all(
            any(_numeric(field_value(row, field)) for row in rows) for field in radar_fields
        ):
            return False, "invalid_radar_dimensions"
        return True, None
    if not x_field or not y_field:
        return False, "missing_axes"

    if chart_type in {"heatmap", "contour"}:
        if not z_field:
            return False, "missing_z_axis"
        if len({x_field, y_field, z_field}) < 3:
            return False, "axes_must_be_distinct"
        usable = _eligible_rows(rows, x_field, y_field, z_field)
        dependent_field = z_field
    else:
        usable = _eligible_rows(
            rows, x_field, y_field,
            categorical_x=chart_type == "bar",
        )
        dependent_field = y_field

    if not usable:
        return False, "missing_numeric_axes"

    units = _units(usable, dependent_field)
    if len(units) > 1:
        return False, "incompatible_value_units"

    if chart_type in {"line", "scatter"}:
        if len(usable) < 2 or len({field_value(row, x_field) for row in usable}) < 2:
            return False, "insufficient_numeric_x_variation"

    if chart_type in {"heatmap", "contour"}:
        xs = {field_value(row, x_field) for row in usable}
        ys = {field_value(row, y_field) for row in usable}
        coordinates = {(field_value(row, x_field), field_value(row, y_field)) for row in usable}
        minimum = 4 if chart_type == "contour" else 3
        if len(usable) < minimum or len(coordinates) < minimum or len(xs) < 2 or len(ys) < 2:
            return False, "insufficient_data_density"
    return True, None


def build_visualization_spec(
    rows: list[AnalyticMeasurementRow],
    chart_type: str,
    title: str,
    *,
    x_field: str | None = None,
    y_field: str | None = "value",
    z_field: str | None = None,
    series_field: str | None = None,
    subtitle: str | None = None,
    query: AnalyticQuery | None = None,
    radar_fields: list[str] | None = None,
    radar_normalization_policy: str | None = None,
) -> VisualizationSpec:
    radar_fields = radar_fields or []
    eligible, reason = _eligibility(
        chart_type,
        rows,
        x_field,
        y_field,
        z_field,
        radar_fields,
        radar_normalization_policy,
    )
    record_ids = [
        (row.archive_id, row.experiment_id, row.calculation_id, row.property_name)
        for row in rows
    ]
    visualization_id = stable_id(
        "viz",
        query.model_dump() if query else {},
        chart_type,
        x_field,
        y_field,
        z_field,
        series_field,
        record_ids,
    )
    references = [
        {
            "archive_id": row.archive_id,
            "source_id": row.source_id,
            "experiment_id": row.experiment_id,
            "calculation_id": row.calculation_id,
            "evidence": row.evidence_references,
        }
        for row in rows
    ]
    units: dict[str, str] = {}
    for axis, field in (("x", x_field), ("y", y_field), ("z", z_field)):
        field_units = _units(rows, field)
        if len(field_units) == 1:
            units[axis] = next(iter(field_units))
    warnings: list[str] = []
    if chart_type == "contour" and eligible:
        warnings.append(
            "Contour shading interpolates visually between observed source-linked points; no interpolated values are added to the archive."
        )
    return VisualizationSpec(
        visualization_id=visualization_id,
        chart_type=chart_type,
        title=title,
        subtitle=subtitle,
        x_field=x_field,
        y_field=y_field,
        z_field=z_field,
        series_field=series_field,
        x_label=x_field,
        y_label=y_field,
        z_label=z_field,
        units=units,
        filters_applied=query.model_dump(exclude_none=True) if query else {},
        source_count=len({row.source_id for row in rows if row.source_id}),
        record_count=len(rows),
        provenance_references=references,
        rendering_warnings=warnings,
        eligible=eligible,
        reason=reason,
        radar_fields=radar_fields,
        radar_normalization_policy=radar_normalization_policy,
    )
