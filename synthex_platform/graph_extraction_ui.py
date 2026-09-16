from __future__ import annotations

import csv
import hashlib
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
GRAPH_WORKSPACE_STATE_KEYS = (
    "digitization_graph_image",
    "synthex_graph_image_token",
    "synthex_graph_plot_selection",
    "synthex_graph_curve_selection",
    "synthex_graph_plot_bounds",
    "synthex_graph_curve_sample",
)


def _clear_graph_workspace_state(state) -> None:
    """Clear graph-upload and interactive-selection state without touching other Synthex workspaces."""
    for key in GRAPH_WORKSPACE_STATE_KEYS:
        state.pop(key, None)


def _reset_graph_workspace() -> None:
    _clear_graph_workspace_state(st.session_state)


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


def _drag_bounds(
    value: dict | None,
    scale_x: float,
    scale_y: float,
    *,
    display_width: int | None = None,
    display_height: int | None = None,
) -> tuple[float, float, float, float] | None:
    if not value or not all(key in value for key in ("x1", "y1", "x2", "y2")):
        return None
    x1, y1, x2, y2 = (float(value[key]) for key in ("x1", "y1", "x2", "y2"))
    if display_width is not None:
        x1 = min(max(x1, 0.0), float(display_width - 1))
        x2 = min(max(x2, 0.0), float(display_width - 1))
    if display_height is not None:
        y1 = min(max(y1, 0.0), float(display_height - 1))
        y2 = min(max(y2, 0.0), float(display_height - 1))
    x1, y1 = _native_point(x1, y1, scale_x, scale_y)
    x2, y2 = _native_point(x2, y2, scale_x, scale_y)
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


def _selection_overlay(
    image: Image.Image,
    *,
    drag_value: dict | None = None,
    point_value: dict | None = None,
) -> Image.Image:
    """Draw persistent selection feedback on the interactive display image."""
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    line_width = max(2, round(min(canvas.size) / 220))

    if drag_value and all(key in drag_value for key in ("x1", "y1", "x2", "y2")):
        x1 = min(max(float(drag_value["x1"]), 0.0), float(canvas.width - 1))
        x2 = min(max(float(drag_value["x2"]), 0.0), float(canvas.width - 1))
        y1 = min(max(float(drag_value["y1"]), 0.0), float(canvas.height - 1))
        y2 = min(max(float(drag_value["y2"]), 0.0), float(canvas.height - 1))
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right > left and bottom > top:
            draw.rectangle(
                (left, top, right, bottom),
                fill=(255, 76, 76, 28),
                outline=(255, 76, 76, 255),
                width=line_width,
            )

    if point_value and "x" in point_value and "y" in point_value:
        x = min(max(float(point_value["x"]), 0.0), float(canvas.width - 1))
        y = min(max(float(point_value["y"]), 0.0), float(canvas.height - 1))
        radius = max(5, round(min(canvas.size) / 75))
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(255, 255, 255, 220),
            outline=(255, 76, 76, 255),
            width=line_width,
        )
        draw.line((x - radius, y, x + radius, y), fill=(255, 76, 76, 255), width=line_width)
        draw.line((x, y - radius, x, y + radius), fill=(255, 76, 76, 255), width=line_width)

    return Image.alpha_composite(canvas, overlay).convert("RGB")


def _axis_calibration_error(axis: str, start: float, end: float, is_log: bool) -> str | None:
    if start == end:
        return f"{axis}-axis calibration needs two different values."
    if is_log and (start <= 0 or end <= 0):
        return (
            f"{axis}-axis is marked logarithmic, so both calibration values must be greater than 0. "
            f"Untick the logarithmic option if the published axis is linear."
        )
    return None


def _selection_signature(value: dict | None, keys: tuple[str, ...]) -> tuple[float, ...] | None:
    if not value or not all(key in value for key in keys):
        return None
    return tuple(float(value[key]) for key in keys)


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
    top_left, top_right = st.columns([3, 1], vertical_alignment="center")
    with top_left:
        st.subheader("Extract Data from Graphs")
        st.write(
            "Recover approximate numerical data from a plotted curve when a paper shows the result in a graph "
            "but does not provide the underlying table."
        )
    with top_right:
        st.button(
            "Reset graph",
            icon=":material/refresh:",
            width="stretch",
            on_click=_reset_graph_workspace,
        )

    st.info(
        "Digitized values are estimates from the figure. Synthex keeps them separate from exact, source-reported "
        "numerical data and labels them as estimated."
    )

    with st.expander("How it works"):
        st.write(
            "1. Upload a clear graph or single figure panel.\n"
            "2. Drag across the interior plotting rectangle.\n"
            "3. Click directly on the curve you want Synthex to trace.\n"
            "4. Enter the visible X and Y axis limits.\n"
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

    image_token = hashlib.sha256(image_bytes).hexdigest()
    if st.session_state.get("synthex_graph_image_token") != image_token:
        st.session_state["synthex_graph_image_token"] = image_token
        st.session_state["synthex_graph_plot_selection"] = None
        st.session_state["synthex_graph_curve_selection"] = None

    try:
        from streamlit_image_coordinates import streamlit_image_coordinates
    except ImportError:
        logger.exception("Interactive graph coordinate component is unavailable")
        st.info("Interactive graph calibration is temporarily unavailable. You can still use Manual calibration below.")
        streamlit_image_coordinates = None

    stored_drag = st.session_state.get("synthex_graph_plot_selection")
    stored_curve = st.session_state.get("synthex_graph_curve_selection")
    interactive_bounds = _drag_bounds(
        stored_drag,
        scale_x,
        scale_y,
        display_width=display_image.width,
        display_height=display_image.height,
    )
    sampled_rgb = _sample_rgb(image, stored_curve, scale_x, scale_y)

    if streamlit_image_coordinates is not None:
        st.markdown("### 2 · Select the plotting area")
        st.caption(
            "Drag from one corner of the inner graph rectangle to the opposite corner. "
            "The selected region will remain highlighted."
        )
        bounds_image = _selection_overlay(display_image, drag_value=stored_drag)
        drag_value = streamlit_image_coordinates(
            bounds_image,
            key="synthex_graph_plot_bounds",
            click_and_drag=True,
            cursor="crosshair",
        )
        new_drag_signature = _selection_signature(drag_value, ("x1", "y1", "x2", "y2"))
        old_drag_signature = _selection_signature(stored_drag, ("x1", "y1", "x2", "y2"))
        if new_drag_signature is not None and new_drag_signature != old_drag_signature:
            st.session_state["synthex_graph_plot_selection"] = {
                key: drag_value[key] for key in ("x1", "y1", "x2", "y2")
            }
            st.rerun()
        if interactive_bounds:
            st.success("Plot area selected and highlighted.")
        else:
            st.caption("Drag across the graph to select its plotting area.")

        st.markdown("### 3 · Select the curve")
        st.caption("Click directly on a clear section of the coloured line or marker series.")
        curve_image = _selection_overlay(display_image, drag_value=stored_drag, point_value=stored_curve)
        curve_value = streamlit_image_coordinates(
            curve_image,
            key="synthex_graph_curve_sample",
            cursor="crosshair",
        )
        new_curve_signature = _selection_signature(curve_value, ("x", "y"))
        old_curve_signature = _selection_signature(stored_curve, ("x", "y"))
        if new_curve_signature is not None and new_curve_signature != old_curve_signature:
            st.session_state["synthex_graph_curve_selection"] = {
                key: curve_value[key] for key in ("x", "y")
            }
            st.rerun()
        if sampled_rgb:
            swatch = "#{:02X}{:02X}{:02X}".format(*sampled_rgb)
            st.success(f"Curve selected and marked · sampled colour {swatch}")
        else:
            st.caption("Click a curve to sample its colour.")

        controls = st.columns(2)
        with controls[0]:
            if st.button("Clear plot selection", key="synthex_clear_plot_selection"):
                st.session_state["synthex_graph_plot_selection"] = None
                st.rerun()
        with controls[1]:
            if st.button("Clear curve selection", key="synthex_clear_curve_selection"):
                st.session_state["synthex_graph_curve_selection"] = None
                st.rerun()

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
            x_log = st.checkbox(
                "X axis uses a logarithmic scale",
                help="Enable only if the published X axis is logarithmic. Logarithmic calibration values must be greater than 0.",
            )
        with scale_right:
            y_log = st.checkbox(
                "Y axis uses a logarithmic scale",
                help="Enable only if the published Y axis is logarithmic. Logarithmic calibration values must be greater than 0.",
            )

        st.caption("Only enable logarithmic scale when the published graph actually uses it. A log axis cannot include 0 or negative calibration values.")

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

    x_error = _axis_calibration_error("X", float(x0), float(x1), bool(x_log))
    y_error = _axis_calibration_error("Y", float(y0), float(y1), bool(y_log))
    if x_error or y_error:
        for message in (x_error, y_error):
            if message:
                st.warning(message)
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
