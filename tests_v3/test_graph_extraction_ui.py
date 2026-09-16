from pathlib import Path

from synthex_platform.graph_extraction_ui import _figure_id, _hex_to_rgb, _rows_csv


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


def test_graph_ui_hides_pixel_and_rgb_controls_by_default():
    source = Path("synthex_platform/graph_extraction_ui.py").read_text(encoding="utf-8")
    assert 'st.color_picker(' in source
    assert 'with st.expander("Advanced calibration")' in source
    assert "Selected series RGB" not in source
    assert "Estimated from figure" in source
    assert "Download estimated CSV" in source
    assert "detected points overlaid" in source


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
