from pathlib import Path

from PIL import Image

from synthex_platform.graph_extraction_ui import (
    GRAPH_WORKSPACE_STATE_KEYS,
    _axis_calibration_error,
    _clear_graph_workspace_state,
    _drag_bounds,
    _figure_id,
    _hex_to_rgb,
    _interactive_image,
    _native_point,
    _rows_csv,
    _sample_rgb,
    _selection_overlay,
)


def test_home_hides_internal_saved_archive_counter():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    home = source.split('elif page == "Discover Papers":', 1)[0]
    assert 'metric("Saved archives"' not in home
    assert 'metric("Scientific domains"' in home
    assert 'metric("Batch capacity"' in home


def test_graph_workspace_uses_researcher_facing_label_and_renderer():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    assert 'elif page == "Extract Data from Graphs":' in source
    assert "render_graph_extraction_ui()" in source
    assert 'elif page == "Figure Data":' not in source


def test_graph_ui_uses_interactive_selection_and_keeps_manual_fallback():
    source = Path("synthex_platform/graph_extraction_ui.py").read_text(encoding="utf-8")
    assert "streamlit_image_coordinates" in source
    assert "click_and_drag=True" in source
    assert 'cursor="crosshair"' in source
    assert 'with st.expander("Manual calibration")' in source
    assert "Use manual plot bounds and curve colour" in source
    assert "Plot area selected and highlighted" in source
    assert "Curve selected and marked" in source
    assert "Clear plot selection" in source
    assert "Clear curve selection" in source
    assert "Selected series RGB" not in source
    assert "Estimated from figure" in source
    assert "Download estimated CSV" in source
    assert "detected points overlaid" in source


def test_graph_workspace_has_reset_button_and_scoped_state_clearer():
    source = Path("synthex_platform/graph_extraction_ui.py").read_text(encoding="utf-8")
    assert '"Reset graph"' in source
    assert 'icon=":material/refresh:"' in source
    assert "on_click=_reset_graph_workspace" in source

    state = {key: f"value-{index}" for index, key in enumerate(GRAPH_WORKSPACE_STATE_KEYS)}
    state["synthex_last_archive"] = "keep-me"
    _clear_graph_workspace_state(state)
    assert all(key not in state for key in GRAPH_WORKSPACE_STATE_KEYS)
    assert state["synthex_last_archive"] == "keep-me"


def test_interactive_coordinate_helpers_map_display_pixels_to_native_image():
    image = Image.new("RGB", (2000, 1000), (255, 255, 255))
    display, scale_x, scale_y = _interactive_image(image, max_width=1000)
    assert display.size == (1000, 500)
    assert (scale_x, scale_y) == (2.0, 2.0)
    assert _native_point(100, 50, scale_x, scale_y) == (200.0, 100.0)
    bounds = _drag_bounds({"x1": 400, "y1": 300, "x2": 100, "y2": 50}, scale_x, scale_y)
    assert bounds == (200.0, 100.0, 800.0, 600.0)


def test_drag_bounds_clamp_release_outside_image():
    bounds = _drag_bounds(
        {"x1": 10, "y1": 20, "x2": 1200, "y2": 700},
        2.0,
        2.0,
        display_width=1000,
        display_height=500,
    )
    assert bounds == (20.0, 40.0, 1998.0, 998.0)


def test_curve_click_samples_native_rgb_after_display_scaling():
    image = Image.new("RGB", (20, 10), (255, 255, 255))
    image.putpixel((10, 4), (12, 34, 56))
    assert _sample_rgb(image, {"x": 5, "y": 2}, 2.0, 2.0) == (12, 34, 56)
    assert _sample_rgb(image, None, 1.0, 1.0) is None


def test_selection_overlay_visibly_marks_rectangle_and_curve_point():
    image = Image.new("RGB", (100, 80), (255, 255, 255))
    marked = _selection_overlay(
        image,
        drag_value={"x1": 10, "y1": 10, "x2": 80, "y2": 60},
        point_value={"x": 40, "y": 30},
    )
    assert marked.size == image.size
    assert marked.tobytes() != image.tobytes()


def test_log_axis_validation_explains_zero_values_before_digitization():
    assert _axis_calibration_error("X", 0.0, 10.0, True) is not None
    assert "greater than 0" in _axis_calibration_error("Y", 0.0, 10.0, True)
    assert _axis_calibration_error("X", 0.0, 10.0, False) is None
    assert _axis_calibration_error("X", 0.1, 10.0, True) is None
    assert "two different values" in _axis_calibration_error("X", 1.0, 1.0, False)


def test_graph_ui_helpers_preserve_estimated_export_semantics():
    assert _figure_id("5a") == "fig-5a"
    assert _figure_id("fig-7") == "fig-7"
    assert _hex_to_rgb("#E41A1C") == (228, 26, 28)
    data = _rows_csv([
        {
            "series": "series-user",
            "x": 1.0,
            "y": 2.0,
            "confidence": 0.9,
            "estimated": True,
            "origin": "figure_digitized",
            "evidence_strength": "estimated_digitized",
        }
    ]).decode("utf-8")
    assert "estimated" in data
    assert "figure_digitized" in data
    assert "estimated_digitized" in data
