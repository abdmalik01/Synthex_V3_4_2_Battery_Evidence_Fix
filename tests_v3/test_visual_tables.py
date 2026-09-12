from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from synthex_platform.visual.models import BoundingBox, TableCell, TableRecord, VisualProvenance
from synthex_platform.visual.tables import extract_tables
from synthex_platform.visual.tables.normalize import normalize_table


FIXTURE = Path(__file__).parent / "fixtures" / "visual" / "native_table.json"


def _draw_table(path, *, caption: str | None = None):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document = pymupdf.open()
    page = document.new_page(width=600, height=400)
    if caption:
        page.insert_text((72, 55), caption)
    x0, y0, width, height = 72, 85, 460, 90
    columns, rows = 4, 2
    cell_width, cell_height = width / columns, height / rows
    for col in range(columns + 1):
        x = x0 + col * cell_width
        page.draw_line((x, y0), (x, y0 + height))
    for row in range(rows + 1):
        y = y0 + row * cell_height
        page.draw_line((x0, y), (x0 + width, y))
    ascii_headers = ["Sample", "Temp (C)", "Capacity (mAh/g)", "D (cm2/s)"]
    ascii_row = ["Li2FeTiO4", "700 C", "121.3 mAh/g", "1.096 x 10-12 cm2/s"]
    for row_index, values in enumerate((ascii_headers, ascii_row)):
        for col_index, value in enumerate(values):
            page.insert_text((x0 + 4 + col_index * cell_width, y0 + 27 + row_index * cell_height), value, fontsize=7)
    document.save(path)
    document.close()
    return data


def test_native_table_retains_grid_order_bbox_caption_and_stable_id(tmp_path):
    path = tmp_path / "table.pdf"
    _draw_table(path, caption="Table 1. Electrochemical performance.")
    first = extract_tables(path, source_id="src-fixture")
    second = extract_tables(path, source_id="src-fixture")
    assert len(first) == 1
    table = first[0]
    assert table.table_id == second[0].table_id
    assert table.page == 1 and table.parser == "pymupdf"
    assert table.bbox is not None
    assert table.caption == "Table 1. Electrochemical performance."
    assert table.table_number == "1"
    assert table.raw_representation["grid"][0][0] == "Sample"
    assert table.raw_representation["grid"][1][0] == "Li2FeTiO4"
    assert [(cell.row, cell.column) for cell in table.cells[:4]] == [(0, 0), (0, 1), (0, 2), (0, 3)]
    assert table.column_units


def test_no_caption_and_no_table_are_not_fabricated(tmp_path):
    table_path = tmp_path / "uncaptioned.pdf"
    _draw_table(table_path)
    table = extract_tables(table_path)[0]
    assert table.caption is None and table.table_number is None

    empty_path = tmp_path / "no_table.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "This is ordinary prose, not a structured table.")
    document.save(empty_path)
    document.close()
    assert extract_tables(empty_path) == []


def test_normalization_preserves_raw_scientific_fixture_and_ambiguous_headers():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = [data["headers"], data["row"]]
    normalized = normalize_table(raw[1:], [raw[0]])
    assert raw[1][0] == "Li₂FeTiO₄"
    assert raw[1][3] == "1.096 × 10⁻¹² cm²/s"
    assert normalized["row_mappings"][0]["Sample"] == "Li₂FeTiO₄"
    multi_level = normalize_table(raw[1:], [["Performance", None], ["Sample", "Capacity"]])
    assert multi_level["status"] == "partial"
    assert raw[0][2] == "Capacity (mAh/g)"


def test_models_round_trip_and_preserve_span_metadata():
    bbox = BoundingBox(x0=1, y0=2, x1=3, y1=4)
    provenance = VisualProvenance(source_id="src-1", page=1, object_id="tbl-1", bbox=bbox, row=0, column=0, raw_text="Li₂FeTiO₄")
    cell = TableCell(row=0, column=0, raw_text="Li₂FeTiO₄", text="Li₂FeTiO₄", bbox=bbox, row_span=2, column_span=3, provenance=provenance)
    record = TableRecord(table_id="tbl-1", source_id="src-1", page=1, cells=[cell], bbox=bbox, provenance=provenance)
    restored = TableRecord.model_validate_json(record.model_dump_json())
    assert restored.cells[0].row_span == 2
    assert restored.cells[0].column_span == 3
    assert restored.cells[0].provenance.raw_text == "Li₂FeTiO₄"
