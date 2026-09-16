from __future__ import annotations

import csv
import io
import logging

import streamlit as st
from PIL import Image, ImageDraw

from synthex_platform.visual.digitization import (
    AxisCalibration,
    DigitizationRequest,
    PlotArea,
    SeriesSelection,
    digitize_plot,
)
from synthex_platform.visual.digitization.models import PixelBoundingBox

logger = logging.getLogger("synthex.graph_extraction_ui")


def _figure_id(label: str) -> str:
    token = (label or "selected").strip()
    token = "-".join(part for part in token.replace("/", "-").split() if part)
    if not token:
        token = "selected"
    return token if token.startswith("fig-") else f"fig-{token}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError("Curve colour must be a six-digit hex colour.")
    return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))


def _result_rows(result) -> list[dict]:
    rows: list[dict] = []
    for series in result.series:
        for point in series.points:
            rows.append({
                "series": series.series_label or series.series_id,
                "x": point.x,
                "y": point.y,
                "confidence": point.confidence,
                "estimated": True,
                "origin": point.origin,
                "evidence_strength": point.evidence_strength,
            })
    return rows


def _rows_csv(rows: list[dict]) -> bytes:
    output = io.StringIO()
    fieldnames = ["series", "x", "y", "confidence", "estimated", "origin", "evidence_strength"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _preview_image(image_bytes: bytes, result, color: tuple[int, int, int]) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    radius = max(2, round(min(image.size) / 180))
    for series in result.series:
        for point in series.points:
            x = float(point.raw_pixel_x)
            y = float(point.raw_pixel_y)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_graph_extraction_ui() -> None:
    """Render the public graph digitization workflow without exposing pixel/RGB machinery by default."""
    st.subheader("Extract Data from Graphs")
    st.write(
        "Recover approximate numerical data from a plotted curve when a paper shows the result in a graph "
        "but does not provide the underlying table."
    )
    st.info(
        "Digitized values are estimates from the figure. Synthex keeps them separate from exact, source-reported "
        "numerical data and labels them as estimated."
    )

    with st.expander("How it works"):
        st.write(
            "1. Upload a clear graph or a single figure panel.\n"
            "2. Enter the visible minimum and maximum values for the X and Y axes.\n"
            "3. Choose the colour of the curve you want to trace.\n"
            "4. Preview the detected points, then export them as CSV or JSON."
        )
        st.caption(
            "If the plotting rectangle does not fill the image, open Advanced calibration and enter the inner plot bounds."
        )

    st.markdown("### 1 · Upload a graph")
    image_file = st.file_uploader(
        "Graph or figure panel",
        type=["png", "jpg", "jpeg"],
        key="digitization_graph_image",
        help="A cropped single-panel image usually gives the cleanest result.",
    )
    if not image_file:
        return

    image_bytes = image_file.getvalue()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    st.image(image_bytes, caption="Uploaded graph")

    with st.form("graph_digitization_calibration"):
        st.markdown("### 2 · Tell Synthex what the axes mean")
        source_id = st.text_input(
            "Paper/source label",
            value="source-figure",
            help="A short label that lets you trace the exported points back to their paper.",
        )
        figure_label = st.text_input(
            "Figure label",
            value="1",
            help="For example: 5, 5a, or Figure-5a.",
        )
        panel = st.text_input("Panel label (optional)") or None

        x_left_col, x_right_col = st.columns(2)
        with x_left_col:
            x0 = st.number_input("X-axis value at the left", value=0.0)
        with x_right_col:
            x1 = st.number_input("X-axis value at the right", value=1.0)

        y_bottom_col, y_top_col = st.columns(2)
        with y_bottom_col:
            y0 = st.number_input("Y-axis value at the bottom", value=0.0)
        with y_top_col:
            y1 = st.number_input("Y-axis value at the top", value=1.0)

        scale_left, scale_right = st.columns(2)
        with scale_left:
            x_log = st.checkbox("X axis uses a logarithmic scale")
        with scale_right:
            y_log = st.checkbox("Y axis uses a logarithmic scale")

        st.markdown("### 3 · Choose the curve to trace")
        curve_color = st.color_picker(
            "Curve colour",
            value="#E41A1C",
            help="Choose the colour that most closely matches the plotted series you want to recover.",
        )

        with st.expander("Advanced calibration"):
            st.caption(
                "Most users can leave these values alone for a tightly cropped graph. Adjust them only when axes, labels, "
                "legends or margins sit outside the actual plotting rectangle."
            )
            plot_x0 = st.number_input("Plot left boundary (pixels)", min_value=0.0, value=0.0)
            plot_y0 = st.number_input("Plot top boundary (pixels)", min_value=0.0, value=0.0)
            plot_x1 = st.number_input("Plot right boundary (pixels)", min_value=1.0, value=float(width))
            plot_y1 = st.number_input("Plot bottom boundary (pixels)", min_value=1.0, value=float(height))

        submitted = st.form_submit_button("Extract estimated data", type="primary")

    if not submitted:
        return

    try:
        rgb = _hex_to_rgb(curve_color)
        request = DigitizationRequest(
            source_id=source_id.strip() or "source-figure",
            page=1,
            figure_id=_figure_id(figure_label),
            panel=panel,
            plot_area=PlotArea(
                bbox=PixelBoundingBox(x0=plot_x0, y0=plot_y0, x1=plot_x1, y1=plot_y1),
                resolution_width=width,
                resolution_height=height,
            ),
            x_axis=AxisCalibration(
                axis="x",
                pixel_start=plot_x0,
                pixel_end=plot_x1,
                data_start=x0,
                data_end=x1,
                scale_type="log10" if x_log else "linear",
            ),
            y_axis=AxisCalibration(
                axis="y",
                pixel_start=plot_y1,
                pixel_end=plot_y0,
                data_start=y0,
                data_end=y1,
                scale_type="log10" if y_log else "linear",
            ),
            series=[SeriesSelection(series_id="series-user", color_rgb=rgb, association_status="ambiguous")],
        )
        result = digitize_plot(image_bytes, request)
    except Exception as exc:
        logger.exception("Graph digitization failed: %s", exc)
        st.info("We couldn't process this graph with the current calibration. Please check the axis values and try again.")
        return

    if result.status != "completed":
        logger.warning("Graph digitization rejected: %s", result.rejection_reasons)
        st.info(
            "Synthex couldn't trace this curve reliably. Try a more tightly cropped graph, choose a closer curve colour, "
            "or adjust Advanced calibration."
        )
        return

    rows = _result_rows(result)
    st.success(f"Recovered {len(rows)} estimated data point(s).")
    st.caption("Estimated from figure — digitized values are not source-reported exact numerical data.")

    if rows:
        st.markdown("### 4 · Review the extracted points")
        st.dataframe(rows, hide_index=True, width="stretch")
        try:
            preview = _preview_image(image_bytes, result, rgb)
            st.image(preview, caption="Preview — detected points overlaid on the uploaded graph")
        except Exception as exc:
            logger.exception("Graph digitization preview failed: %s", exc)

        with st.container(horizontal=True):
            st.download_button(
                "Download estimated CSV",
                _rows_csv(rows),
                f"{result.digitization_id}.csv",
                "text/csv",
                icon=":material/table_view:",
            )
            st.download_button(
                "Download digitization JSON",
                result.model_dump_json(indent=2),
                f"{result.digitization_id}.json",
                "application/json",
                icon=":material/download:",
            )
