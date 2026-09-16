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
MAX_INTERACTIVE_WIDTH = 1000


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


def _interactive_image(image: Image.Image, max_width: int = MAX_INTERACTIVE_WIDTH) -> tuple[Image.Image, float, float]:
    """Return a display-sized image and scale factors back to native pixels."""
    width, height = image.size
    if width <= max_width:
        return image.copy(), 1.0, 1.0
    display_width = max_width
    display_height = max(1, round(height * display_width / width))
    display = image.resize((display_width, display_height), Image.Resampling.LANCZOS)
    return display, width / display_width, height / display_height


def _native_point(x: float, y: float, scale_x: float, scale_y: float) -> tuple[float, float]:
    return float(x) * scale_x, float(y) * scale_y


def _drag_bounds(value: dict | None, scale_x: float, scale_y: float) -> tuple[float, float, float, float] | None:
    if not value or not all(key in value for key in ("x1", "y1", "x2", "y2")):
        return None
    x1, y1 = _native_point(value["x1"], value["y1"], scale_x, scale_y)
    x2, y2 = _native_point(value["x2"], value["y2"], scale_x, scale_y)
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _sample_rgb(image: Image.Image, value: dict | None, scale_x: float, scale_y: float) -> tuple[int, int, int] | None:
    if not value or "x" not in value or "y" not in value:
        return None
    x, y = _native_point(value["x"], value["y"], scale_x, scale_y)
    px = min(max(int(round(x)), 0), image.width - 1)
    py = min(max(int(round(y)), 0), image.height - 1)
    pixel = image.convert("RGB").getpixel((px, py))
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


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
    """Render click/drag graph calibration while keeping manual calibration as a fallback."""
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
            "1. Upload a clear graph or single figure panel.\n"
            "2. Drag across the interior plotting rectangle.\n"
            "3. Enter the visible X and Y axis limits.\n"
            "4. Click directly on the curve you want Synthex to trace.\n"
            "5. Review the detected points and export them as CSV or JSON."
        )

    st.markdown("### 1 · Upload a graph")
    image_file = st.file_uploader(
        "Graph or figure panel",
        type=["png", "jpg", "jpeg"],
        key="digitization_graph_image",
        help="A clear single-panel image gives the cleanest result.",
    )
    if not image_file:
        return

    image_bytes = image_file.getvalue()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    display_image, scale_x, scale_y = _interactive_image(image)

    try:
        from streamlit_image_coordinates import streamlit_image_coordinates
    except ImportError:
        logger.exception("Interactive graph coordinate component is unavailable")
        st.info("Interactive graph calibration is temporarily unavailable. You can still use Manual calibration below.")
        streamlit_image_coordinates = None

    interactive_bounds = None
    sampled_rgb = None
    if streamlit_image_coordinates is not None:
        st.markdown("### 2 · Select the plotting area")
        st.caption("Drag from one corner of the inner graph rectangle to the opposite corner. Exclude titles, legends and axis labels.")
        drag_value = streamlit_image_coordinates(
            display_image,
            key="synthex_graph_plot_bounds",
            click_and_drag=True,
            cursor="crosshair",
        )
        interactive_bounds = _drag_bounds(drag_value, scale_x, scale_y)
        if interactive_bounds:
            st.success("Plot area selected.")
        else:
            st.caption("Drag across the graph to select its plotting area.")

        st.markdown("### 3 · Select the curve")
        st.caption("Click directly on the coloured line or marker series you want Synthex to recover.")
        curve_value = streamlit_image_coordinates(
            display_image,
            key="synthex_graph_curve_sample",
            cursor="crosshair",
        )
        sampled_rgb = _sample_rgb(image, curve_value, scale_x, scale_y)
        if sampled_rgb:
            swatch = "#{:02X}{:02X}{:02X}".format(*sampled_rgb)
            st.success(f"Curve colour sampled: {swatch}")
        else:
            st.caption("Click a curve to sample its colour.")

    with st.form("graph_digitization_calibration"):
        st.markdown("### 4 · Calibrate the axes")
        source_id = st.text_input(
            "Paper/source label",
            value="source-figure",
            help="A short label that lets you trace the exported points back to their paper.",
        )
        figure_label = st.text_input("Figure label", value="1", help="For example: 5, 5a, or Figure-5a.")
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

        with st.expander("Manual calibration"):
            st.caption("Fallback controls. Use these only if interactive selection is unavailable or needs correction.")
            manual_override = st.checkbox("Use manual plot bounds and curve colour")
            plot_x0_manual = st.number_input("Plot left boundary (pixels)", min_value=0.0, value=0.0)
            plot_y0_manual = st.number_input("Plot top boundary (pixels)", min_value=0.0, value=0.0)
            plot_x1_manual = st.number_input("Plot right boundary (pixels)", min_value=1.0, value=float(width))
            plot_y1_manual = st.number_input("Plot bottom boundary (pixels)", min_value=1.0, value=float(height))
            manual_color = st.color_picker("Curve colour", value="#E41A1C")

        submitted = st.form_submit_button("Extract estimated data", type="primary")

    if not submitted:
        return

    try:
        if manual_override:
            plot_x0, plot_y0, plot_x1, plot_y1 = (
                plot_x0_manual, plot_y0_manual, plot_x1_manual, plot_y1_manual
            )
            rgb = _hex_to_rgb(manual_color)
        else:
            if interactive_bounds is None:
                st.info("Select the plotting area above, or enable Manual calibration.")
                return
            if sampled_rgb is None:
                st.info("Click the curve you want to trace above, or enable Manual calibration.")
                return
            plot_x0, plot_y0, plot_x1, plot_y1 = interactive_bounds
            rgb = sampled_rgb

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
                axis="x", pixel_start=plot_x0, pixel_end=plot_x1,
                data_start=x0, data_end=x1, scale_type="log10" if x_log else "linear",
            ),
            y_axis=AxisCalibration(
                axis="y", pixel_start=plot_y1, pixel_end=plot_y0,
                data_start=y0, data_end=y1, scale_type="log10" if y_log else "linear",
            ),
            series=[SeriesSelection(series_id="series-user", color_rgb=rgb, association_status="ambiguous")],
        )
        result = digitize_plot(image_bytes, request)
    except Exception as exc:
        logger.exception("Graph digitization failed: %s", exc)
        st.info("We couldn't process this graph with the current calibration. Please check the selections and axis values and try again.")
        return

    if result.status != "completed":
        logger.warning("Graph digitization rejected: %s", result.rejection_reasons)
        st.info(
            "Synthex couldn't trace this curve reliably. Try selecting the plot area again, click a clearer part of the curve, "
            "or use Manual calibration."
        )
        return

    rows = _result_rows(result)
    st.success(f"Recovered {len(rows)} estimated data point(s).")
    st.caption("Estimated from figure — digitized values are not source-reported exact numerical data.")

    if rows:
        st.markdown("### 5 · Review the extracted points")
        st.dataframe(rows, hide_index=True, width="stretch")
        try:
            preview = _preview_image(image_bytes, result, rgb)
            st.image(preview, caption="Preview — detected points overlaid on the uploaded graph")
        except Exception as exc:
            logger.exception("Graph digitization preview failed: %s", exc)

        with st.container(horizontal=True):
            st.download_button(
                "Download estimated CSV", _rows_csv(rows), f"{result.digitization_id}.csv", "text/csv",
                icon=":material/table_view:",
            )
            st.download_button(
                "Download digitization JSON", result.model_dump_json(indent=2),
                f"{result.digitization_id}.json", "application/json", icon=":material/download:",
            )
