"""Researcher-facing Streamlit panel for source-tracked multidimensional analytics."""

from __future__ import annotations

from typing import Iterable

import streamlit as st

from synthex_platform.core.archive import SynthexArchive
from .exports import comparison_frame
from .models import AnalyticQuery
from .projection import project_archives
from .render import VisualizationRenderer
from .specs import (
    build_visualization_spec,
    chart_field_options,
    numeric_dimension_summary,
    surface_coverage,
)


def _field_label(field: str, property_name: str) -> str:
    if field == "value":
        return property_name.replace("_", " ").title()
    if field == "material_label":
        return "Material"
    text = field.removeprefix("conditions.").replace("_", " ")
    return text[:1].upper() + text[1:]


def _select_field(label: str, fields: list[str], property_name: str, *, key: str):
    return st.selectbox(
        label,
        fields,
        key=key,
        format_func=lambda field: _field_label(field, property_name),
    )


def _default_series(rows, fields: list[str]) -> int:
    if "material_label" not in fields:
        return 0
    materials = {row.material_label for row in rows if row.material_label}
    return fields.index("material_label") + 1 if len(materials) > 1 else 0


def _eligibility_message(reason: str | None) -> str:
    return {
        "no_records": "No admitted numeric observations are available for this property.",
        "missing_axes": "This chart needs additional axes that are not present in the extracted records.",
        "missing_z_axis": "Heatmaps and contours need two numeric independent variables plus a numeric result (Z).",
        "axes_must_be_distinct": "Choose different X, Y, and Z fields.",
        "missing_numeric_axes": "The selected fields do not contain numeric observations in the same records.",
        "insufficient_numeric_x_variation": "The selected X field does not vary across enough observations for this chart.",
        "insufficient_data_density": "There are not enough distinct X/Y observations for a 2D surface view.",
        "incompatible_value_units": "The plotted result contains incompatible units. Filter to one compatible unit before charting.",
    }.get(reason, f"Chart is not eligible: {reason or 'unknown reason'}")


def _render_dimension_coverage(rows, property_name: str) -> None:
    summary = numeric_dimension_summary(rows)
    with st.expander("Numeric dimension coverage", expanded=False):
        if not summary:
            st.caption("No numeric result or condition dimensions are present in the admitted rows.")
            return
        display = [
            {
                "Dimension": _field_label(item["field"], property_name),
                "Numeric observations": item["observations"],
                "Unique values": item["unique_values"],
                "Missing rows": item["missing"],
                "Units": item["units"],
            }
            for item in summary
        ]
        st.dataframe(display, hide_index=True, width="stretch")
        st.caption(
            "Coverage counts only admitted numeric values. A dimension appearing somewhere in the archive does not imply "
            "that it is jointly linked to another dimension on the same observations."
        )


def _render_surface_coverage(rows, property_name: str, x_field, y_field, z_field) -> None:
    if not (x_field and y_field and z_field):
        return
    coverage = surface_coverage(rows, x_field, y_field, z_field)
    st.caption(
        "2D coverage — "
        f"joint X+Y: {coverage['joint_xy']} · "
        f"joint X+Y+Z: {coverage['joint_xyz']} · "
        f"distinct X: {coverage['unique_x']} · "
        f"distinct Y: {coverage['unique_y']} · "
        f"distinct coordinates: {coverage['unique_coordinates']}"
    )
    if coverage["joint_xyz"]:
        st.caption(
            f"Selected dimensions: {_field_label(x_field, property_name)} × "
            f"{_field_label(y_field, property_name)} → {_field_label(z_field, property_name)}."
        )


def render_visual_explorer(archives: Iterable[SynthexArchive]) -> None:
    """Render data-aware bar, line, scatter, heatmap, and contour controls."""
    archives = list(archives)
    all_rows = project_archives(archives)
    properties = sorted({row.property_name for row in all_rows})
    if not properties:
        st.info("No canonical numeric archive measurements are available to visualize.")
        return

    property_name = st.selectbox("Property", properties, key="synthex_viz_property")
    query = AnalyticQuery(property_name=property_name)
    rows = project_archives(archives, query)
    frame = comparison_frame(rows)
    st.caption(
        "Axes are discovered from the admitted source-linked conditions present in these records. "
        "Original source/archive identifiers remain attached."
    )
    st.dataframe(frame, hide_index=True, width="stretch")
    _render_dimension_coverage(rows, property_name)

    chart_type = st.selectbox(
        "Chart type",
        ["bar", "line", "scatter", "heatmap", "contour"],
        key="synthex_viz_chart_type",
    )
    options = chart_field_options(rows, chart_type)

    x_field = y_field = z_field = series_field = None
    if chart_type == "bar":
        if options["x"] and options["y"]:
            x_field = _select_field("X field", options["x"], property_name, key="synthex_viz_bar_x")
            y_candidates = ["value"] + [field for field in options["y"] if field != "value"]
            y_field = _select_field("Y field", y_candidates, property_name, key="synthex_viz_bar_y")
    elif chart_type in {"line", "scatter"}:
        if options["x"] and options["y"]:
            x_field = _select_field(
                "X field (numeric independent variable)",
                options["x"],
                property_name,
                key=f"synthex_viz_{chart_type}_x",
            )
            y_candidates = ["value"] + [field for field in options["y"] if field not in {"value", x_field}]
            y_field = _select_field(
                "Y field",
                y_candidates,
                property_name,
                key=f"synthex_viz_{chart_type}_y",
            )
            series_candidates = ["None"] + options["series"]
            series_choice = st.selectbox(
                "Series / group",
                series_candidates,
                index=_default_series(rows, options["series"]),
                key=f"synthex_viz_{chart_type}_series",
                format_func=lambda field: "None" if field == "None" else _field_label(field, property_name),
            )
            series_field = None if series_choice == "None" else series_choice
    else:
        if len(options["x"]) >= 2 and options["z"]:
            x_field = _select_field(
                "X field (numeric independent variable)",
                options["x"],
                property_name,
                key=f"synthex_viz_{chart_type}_x",
            )
            y_candidates = [field for field in options["y"] if field != x_field]
            if y_candidates:
                y_field = _select_field(
                    "Y field (second numeric independent variable)",
                    y_candidates,
                    property_name,
                    key=f"synthex_viz_{chart_type}_y",
                )
                z_candidates = ["value"] + [
                    field for field in options["z"]
                    if field not in {"value", x_field, y_field}
                ]
                z_field = _select_field(
                    "Z / colour field",
                    z_candidates,
                    property_name,
                    key=f"synthex_viz_{chart_type}_z",
                )

    spec = build_visualization_spec(
        rows,
        chart_type,
        f"{property_name.replace('_', ' ').title()} comparison",
        x_field=x_field,
        y_field=y_field,
        z_field=z_field,
        series_field=series_field,
        query=query,
    )

    if chart_type in {"heatmap", "contour"}:
        _render_surface_coverage(rows, property_name, x_field, y_field, z_field)

    if spec.eligible:
        png = VisualizationRenderer().render_png(spec, rows)
        st.image(png)
        for warning in spec.rendering_warnings:
            st.caption(warning)
        st.download_button(
            "Download chart PNG",
            png,
            f"{spec.visualization_id}.png",
            "image/png",
        )
    else:
        st.warning(_eligibility_message(spec.reason))
        if chart_type in {"line", "scatter"} and not options["x"]:
            st.caption(
                "This property has no numeric independent variable in its admitted records. "
                "A bar chart may still be valid, or another property may expose C-rate, cycle, temperature, "
                "state of charge, synthesis temperature, or another numeric condition."
            )
        elif chart_type in {"heatmap", "contour"} and len(options["x"]) < 2:
            available = [
                _field_label(item["field"], property_name)
                for item in numeric_dimension_summary(rows)
                if item["field"] != "value"
            ]
            available_text = ", ".join(available) if available else "none"
            st.caption(
                "A 2D map needs at least two numeric conditions attached to the same reported values. "
                f"Numeric independent dimensions currently found: {available_text}."
            )
        elif chart_type in {"heatmap", "contour"} and x_field and y_field and z_field:
            coverage = surface_coverage(rows, x_field, y_field, z_field)
            if coverage["unique_x"] < 2 or coverage["unique_y"] < 2:
                st.caption(
                    "The selected dimensions exist, but the jointly linked observations do not vary in both directions. "
                    "Synthex will not combine unrelated rows to manufacture a 2D surface."
                )
            elif coverage["joint_xyz"] < (4 if chart_type == "contour" else 3):
                st.caption(
                    "Too few source-linked XYZ observations remain after requiring all three selected dimensions on the same rows."
                )

    st.download_button(
        "Download comparison CSV",
        frame.to_csv(index=False).encode("utf-8"),
        f"{spec.visualization_id}.csv",
        "text/csv",
    )
