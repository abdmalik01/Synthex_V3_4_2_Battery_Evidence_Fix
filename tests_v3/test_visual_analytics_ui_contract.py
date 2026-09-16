from __future__ import annotations

import ast
from pathlib import Path


def test_primary_app_uses_data_aware_visual_explorer_panel():
    source = Path("platform_app.py").read_text(encoding="utf-8")
    assert ast.parse(source) is not None
    assert "render_visual_explorer" in source
    assert '["material_label", "conditions.temperature", "conditions.cycle"]' not in source


def test_visual_panel_exposes_true_xyz_controls_and_dynamic_field_discovery():
    source = Path("synthex_platform/visual/analytics/streamlit_panel.py").read_text(encoding="utf-8")
    assert ast.parse(source) is not None
    assert "chart_field_options" in source
    assert "X field (numeric independent variable)" in source
    assert "Y field (second numeric independent variable)" in source
    assert "Z / colour field" in source
