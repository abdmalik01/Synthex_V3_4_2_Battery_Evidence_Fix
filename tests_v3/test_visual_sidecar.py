from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import Measurement
from synthex_platform.visual.bridge import with_visual_evidence
from synthex_platform.visual.document import build_visual_document
from synthex_platform.visual.models import VisualClaimCandidate, VisualProvenance
from synthex_platform.visual.sidecar_store import VisualSidecarStore
from synthex_platform.visual.verification import classify_evidence_strength, verify_table_evidence


FIXTURE = Path(__file__).parent / "fixtures" / "visual" / "lfto_table.json"


def _fixture_pdf(path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document = pymupdf.open()
    page = document.new_page(width=680, height=420)
    page.insert_text((72, 55), "Table 2. LFTO electrochemical results.")
    x0, y0, width, height = 50, 85, 580, 160
    columns, rows = len(data["headers"]), len(data["rows"]) + 1
    cell_width, cell_height = width / columns, height / rows
    for col in range(columns + 1):
        page.draw_line((x0 + col * cell_width, y0), (x0 + col * cell_width, y0 + height))
    for row in range(rows + 1):
        page.draw_line((x0, y0 + row * cell_height), (x0 + width, y0 + row * cell_height))
    values = [data["headers"], *data["rows"]]
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            # The JSON fixture preserves Unicode exactly; Helvetica is intentionally
            # avoided for glyph assertions because it is not a Unicode scientific font.
            ascii_value = value.replace("°", "deg").replace("Ω", "Ohm").replace("²", "2").replace("⁻", "-").replace("¹", "1").replace("×", "x")
            page.insert_text((x0 + 3 + column_index * cell_width, y0 + 20 + row_index * cell_height), ascii_value, fontsize=6)
    document.save(path)
    document.close()


def _document(tmp_path):
    path = tmp_path / "lfto.pdf"
    _fixture_pdf(path)
    return build_visual_document(path, "src-lfto")


def _capacity_evidence(document, *, page=1):
    table = document.tables[0]
    cell = next(cell for cell in table.cells if cell.row == 2 and cell.column == 2)
    return VisualProvenance(
        source_id=document.source_id, page=page, object_id=table.table_id, object_type="table",
        row=cell.row, column=cell.column, cell_id=cell.cell_id, parser_or_method="pymupdf", raw_text=cell.raw_text,
    )


def test_sidecar_round_trip_is_deterministic_and_preserves_native_provenance(tmp_path):
    document = _document(tmp_path)
    store = VisualSidecarStore(tmp_path / "sidecars")
    first_path = store.save(document)
    first = first_path.read_text(encoding="utf-8")
    store.save(document)
    assert first == first_path.read_text(encoding="utf-8")
    loaded = store.require("src-lfto")
    assert loaded.tables[0].table_id == document.tables[0].table_id
    assert loaded.figures == [] and loaded.ocr_blocks == []
    assert loaded.tables[0].bbox is not None
    assert loaded.tables[0].provenance.parser_or_method == "pymupdf"
    assert loaded.tables[0].column_units


def test_lookup_and_missing_references_are_explicit(tmp_path):
    document = _document(tmp_path)
    store = VisualSidecarStore(tmp_path / "sidecars")
    store.save(document)
    table = store.require_table("src-lfto", document.tables[0].table_id)
    cell = store.require_cell("src-lfto", table.table_id, row=2, column=2)
    assert cell.raw_text == "121.3 mAh/g"
    assert store.list_objects("src-lfto") == [{"object_id": table.table_id, "object_type": "table"}]
    assert store.get_table("src-lfto", "tbl-missing") is None
    assert store.get_cell("src-lfto", table.table_id, row=99, column=2) is None
    with pytest.raises(KeyError):
        store.require_table("src-lfto", "tbl-missing")
    with pytest.raises(KeyError):
        store.require_cell("src-lfto", table.table_id, row=99, column=2)


def test_generic_verifier_accepts_exact_and_normalized_but_rejects_wrong_values(tmp_path):
    document = _document(tmp_path)
    evidence = _capacity_evidence(document)
    exact = verify_table_evidence(document, "121.3 mAh/g", evidence)
    normalized = verify_table_evidence(document, "  121.3   mAh/g ", evidence)
    wrong = verify_table_evidence(document, "approximately 120", evidence)
    page_mismatch = verify_table_evidence(document, "121.3 mAh/g", evidence.model_copy(update={"page": 2}))
    missing_cell = verify_table_evidence(document, "121.3 mAh/g", evidence.model_copy(update={"cell_id": "missing"}))
    assert exact.verified and exact.match_type == "exact_raw" and exact.evidence_strength == "verified_native"
    assert normalized.verified and normalized.match_type == "normalized_whitespace_or_unicode"
    assert not wrong.verified and wrong.reason == "cell_text_mismatch"
    assert not page_mismatch.verified and page_mismatch.reason == "page_mismatch"
    assert not missing_cell.verified and missing_cell.reason == "cell_not_found"


def test_unicode_fixture_candidate_and_non_mutating_archive_bridge(tmp_path):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["rows"][1][1] == "700 °C"
    assert data["rows"][1][3] == "1258.6 Ω"
    assert data["rows"][1][4] == "1.096 × 10⁻¹² cm²/s"
    document = _document(tmp_path)
    evidence = _capacity_evidence(document)
    result = verify_table_evidence(document, "121.3 mAh/g", evidence)
    candidate = VisualClaimCandidate(raw_value_text="121.3 mAh/g", evidence=evidence)
    restored = VisualClaimCandidate.model_validate_json(candidate.model_dump_json())
    assert restored.proposed_property is None and restored.proposed_value is None
    assert restored.admission_status == "not_submitted"
    original = Measurement(property="specific_capacity", raw_value="121.3 mAh/g")
    archive = SynthexArchive(metadata=ArchiveMetadata(archive_id="arc-visual-bridge"))
    archive_before = archive.model_dump_json()
    copied = with_visual_evidence(original, evidence, result)
    assert original.evidence == []
    assert len(copied.evidence) == 1
    assert archive.model_dump_json() == archive_before
    assert classify_evidence_strength(evidence, True) == "verified_native"
    assert classify_evidence_strength(evidence, False) == "unverified"
