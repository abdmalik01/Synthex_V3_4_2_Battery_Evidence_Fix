"""Researcher-facing Streamlit panel for source-tracked multidimensional analytics."""

from __future__ import annotations

from typing import Iterable

import streamlit as st

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.archive_scoping import (
    ArchiveQueryContext,
    CurrentExtraction,
    DataScope,
    SCOPE_BY_LABEL,
    SCOPE_LABELS,
    THESIS_DOMAIN_LABELS,
    UNKNOWN_LEGACY_DOMAIN,
    VISUAL_SCOPE_STATE_KEY,
    archive_domain,
    archive_source_ids,
    deduplicate_archives,
    domain_catalog,
    select_archives,
)
from .exports import comparison_frame
from .models import AnalyticQuery
from .projection import project_archives
from .render import VisualizationRenderer
from .specs import (
    build_visualization_spec,
    chart_field_options,
    field_display_name,
    numeric_dimension_summary,
    surface_coverage,
)


def _field_label(field: str, property_name: str) -> str:
    return field_display_name(field, property_name)


def _select_field(label: str, fields: list[str], property_name: str, *, key: str, index: int = 0):
    return st.selectbox(
        label,
        fields,
        index=index,
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
        "incompatible_cross_domain_records": "Cross-domain rows cannot be combined into one scientific chart. Select one domain or a domain-compatible subset.",
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
    if coverage["duplicate_coordinates"]:
        st.caption(f"Duplicate X/Y coordinates: {coverage['duplicate_coordinates']}.")
    elif coverage["complete_rectangular_grid"]:
        st.caption("The selected observations form a complete rectangular measurement grid.")


def _archive_choice_label(archive: SynthexArchive) -> str:
    source = archive.sources[0] if archive.sources else None
    title = (source.title if source else None) or archive.metadata.archive_id
    year = getattr(source, "publication_year", None) or getattr(source, "year", None) if source else None
    doi = getattr(source, "doi", None) if source else None
    details = [THESIS_DOMAIN_LABELS.get(archive_domain(archive), archive_domain(archive))]
    if year:
        details.append(str(year))
    if doi:
        details.append(str(doi))
    return f"{title} — {' · '.join(details)}"


def _domain_options(archives: list[SynthexArchive]) -> tuple[list[str], dict[str, str]]:
    extras = sorted(
        {
            (archive_domain(archive), archive_domain(archive).replace("_", " ").title())
            for archive in archives
            if archive_domain(archive) not in THESIS_DOMAIN_LABELS
            and archive_domain(archive) != UNKNOWN_LEGACY_DOMAIN
        }
    )
    catalog = domain_catalog(extras)
    return [slug for slug, _ in catalog], dict(catalog)


def _scope_archives(
    archives: list[SynthexArchive],
    *,
    saved_archives: list[SynthexArchive],
    current_extraction: CurrentExtraction | None,
    current_domain: str | None,
) -> tuple[DataScope, list[SynthexArchive]]:
    labels = [SCOPE_LABELS[scope] for scope in DataScope]
    default = (
        SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]
        if current_extraction
        else SCOPE_LABELS[DataScope.CURRENT_DOMAIN]
        if current_domain
        else SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]
    )
    if st.session_state.get(VISUAL_SCOPE_STATE_KEY) not in labels:
        st.session_state[VISUAL_SCOPE_STATE_KEY] = default
    selected_label = st.selectbox("Data scope", labels, key=VISUAL_SCOPE_STATE_KEY)
    scope = SCOPE_BY_LABEL[selected_label]
    domains, domain_labels = _domain_options(archives)

    if scope == DataScope.CURRENT_EXTRACTION:
        context = ArchiveQueryContext(
            scope=scope,
            run_id=current_extraction.run_id if current_extraction else None,
        )
    elif scope == DataScope.SELECTED_SOURCES:
        saved = deduplicate_archives(saved_archives)
        available_domains = [domain for domain in domains if any(archive_domain(item) == domain for item in saved)]
        if not available_domains:
            return scope, []
        initial = current_domain if current_domain in available_domains else available_domains[0]
        selected_domains = st.multiselect(
            "Archived-paper domains",
            available_domains,
            default=[initial],
            key="synthex_viz_scope_selected_domain",
            format_func=lambda value: domain_labels[value],
        )
        candidates = [item for item in saved if archive_domain(item) in selected_domains]
        labels_by_id = {item.metadata.archive_id: _archive_choice_label(item) for item in candidates}
        selected_ids = st.multiselect(
            "Archived papers",
            list(labels_by_id),
            key="synthex_viz_scope_selected_sources",
            format_func=lambda value: labels_by_id[value],
        )
        source_ids = {
            source_id
            for item in candidates
            if item.metadata.archive_id in selected_ids
            for source_id in archive_source_ids(item)
        }
        context = ArchiveQueryContext(scope=scope, source_ids=source_ids)
    elif scope == DataScope.CURRENT_DOMAIN:
        initial = current_domain if current_domain in domains else domains[0]
        selected_domain = st.selectbox(
            "Domain",
            domains,
            index=domains.index(initial),
            key="synthex_viz_scope_domain",
            format_func=lambda value: domain_labels[value],
        )
        context = ArchiveQueryContext(scope=scope, domain=selected_domain)
    elif scope == DataScope.CUSTOM_COMBINATION:
        labels_by_id = {item.metadata.archive_id: _archive_choice_label(item) for item in archives}
        selected_ids = st.multiselect(
            "Archives to combine",
            list(labels_by_id),
            key="synthex_viz_scope_custom_archives",
            format_func=lambda value: labels_by_id[value],
        )
        context = ArchiveQueryContext(scope=scope, archive_ids=selected_ids)
    else:
        context = ArchiveQueryContext(scope=scope)

    return scope, select_archives(archives, context, current_extraction=current_extraction)


def render_visual_explorer(
    archives: Iterable[SynthexArchive],
    *,
    current_extraction: CurrentExtraction | None = None,
    saved_archives: Iterable[SynthexArchive] = (),
    current_domain: str | None = None,
) -> None:
    """Render data-aware bar, line, scatter, heatmap, and contour controls."""
    archives = deduplicate_archives(archives)
    scope, archives = _scope_archives(
        archives,
        saved_archives=list(saved_archives),
        current_extraction=current_extraction,
        current_domain=current_domain,
    )
    all_rows = [row for row in project_archives(archives) if row.value is not None]
    properties = sorted({row.property_name for row in all_rows})
    if not properties:
        if scope == DataScope.CURRENT_EXTRACTION:
            st.info("No visualization-eligible quantitative records were found in the current extraction.")
            st.caption("Choose another Data scope above to inspect archived papers or a domain explicitly.")
        else:
            st.info("No visualization-eligible quantitative records were found in the selected data scope.")
        return

    source_rows = [
        {
            "Paper": (archive.sources[0].title if archive.sources else None) or archive.metadata.archive_id,
            "Domain": THESIS_DOMAIN_LABELS.get(archive_domain(archive), archive_domain(archive)),
            "Archive ID": archive.metadata.archive_id,
            "Source IDs": ", ".join(sorted(archive_source_ids(archive))),
        }
        for archive in archives
    ]
    st.caption(f"Scoped sources: {len(source_rows)} paper(s) · {len(all_rows)} quantitative record(s)")
    with st.expander("Scoped source details", expanded=False):
        st.dataframe(source_rows, hide_index=True, width="stretch")
    if len({row.domain for row in all_rows if row.domain}) > 1:
        st.warning(
            "This explicit selection spans multiple domains. Synthex will list the scoped records, "
            "but it will refuse a chart that mixes cross-domain rows."
        )

    if st.session_state.get("synthex_viz_property") not in (None, *properties):
        del st.session_state["synthex_viz_property"]
    property_name = st.selectbox("Property", properties, key="synthex_viz_property")
    query = AnalyticQuery(property_name=property_name)
    rows = [row for row in project_archives(archives, query) if row.value is not None]
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
                index=(
                    options["x"].index("conditions.temperature")
                    if "conditions.temperature" in options["x"]
                    else 0
                ),
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

    show_measured_points = False
    if chart_type == "contour" and x_field and y_field and z_field:
        show_measured_points = st.toggle(
            "Show measured points",
            value=True,
            help="Overlay source-reported X/Y coordinates without creating or modifying archive records.",
            key="synthex_viz_contour_measured_points",
        )

    spec = build_visualization_spec(
        rows,
        chart_type,
        None,
        x_field=x_field,
        y_field=y_field,
        z_field=z_field,
        series_field=series_field,
        query=query,
        show_measured_points=show_measured_points,
    )

    if chart_type in {"heatmap", "contour"}:
        _render_surface_coverage(rows, property_name, x_field, y_field, z_field)

    if spec.eligible:
        png = VisualizationRenderer().render_png(spec, rows)
        st.image(png)
        if chart_type == "heatmap":
            coverage = surface_coverage(rows, x_field, y_field, z_field)
            if coverage["complete_rectangular_grid"]:
                st.caption(
                    "Heatmap cells show the complete source-reported measurement grid directly; "
                    "no interpolation was applied."
                )
        elif chart_type == "contour" and spec.show_measured_points:
            st.caption(
                "Outlined markers are source-reported measurements. Their values and source identifiers are listed in the table above."
            )
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
