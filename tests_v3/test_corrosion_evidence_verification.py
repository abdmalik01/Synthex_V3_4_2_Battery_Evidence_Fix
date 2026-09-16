from __future__ import annotations

from synthex_platform.extraction.corrosion_evidence import (
    verify_corrosion_document_evidence,
    verify_corrosion_evidence_item,
)
from synthex_platform.extraction.corrosion_models import CorrosionDocument, CorrosionEvidence
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.visual.models import TableCell, TableRecord, VisualProvenance


def _bundle(*, native_text: str = "", tables: list[TableRecord] | None = None) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-corrosion-test",
            filename="paper.pdf",
            source_checksum="abc123",
        ),
        pages=[SourcePageContext(
            page=6,
            native_text=native_text,
            text=native_text,
            native_parser="pymupdf",
            parser="pymupdf",
            origin="native_text",
            sufficient=True,
        )],
        tables=tables or [],
    )


def _table() -> TableRecord:
    provenance = VisualProvenance(page=6, object_id="tbl-2", object_type="table", origin="table_reported")
    cells = [
        TableCell(
            row=0,
            column=0,
            cell_id="tbl-2-r0-c0",
            raw_text="NaCl concentration",
            provenance=VisualProvenance(page=6, object_id="tbl-2", object_type="table", origin="table_reported", row=0, column=0),
        ),
        TableCell(
            row=0,
            column=1,
            cell_id="tbl-2-r0-c1",
            raw_text="Rs (Ω·cm2)",
            provenance=VisualProvenance(page=6, object_id="tbl-2", object_type="table", origin="table_reported", row=0, column=1),
        ),
        TableCell(
            row=1,
            column=0,
            cell_id="tbl-2-r1-c0",
            raw_text="100 mmol·L-1",
            provenance=VisualProvenance(page=6, object_id="tbl-2", object_type="table", origin="table_reported", row=1, column=0),
        ),
        TableCell(
            row=1,
            column=1,
            cell_id="tbl-2-r1-c1",
            raw_text="75.21",
            provenance=VisualProvenance(page=6, object_id="tbl-2", object_type="table", origin="table_reported", row=1, column=1),
        ),
    ]
    return TableRecord(
        table_id="tbl-2",
        source_id="src-corrosion-test",
        page=6,
        table_number="2",
        caption="Electrochemical impedance parameters",
        cells=cells,
        raw_representation={
            "grid": [
                ["NaCl concentration", "Rs (Ω·cm2)"],
                ["100 mmol·L-1", "75.21"],
            ]
        },
        provenance=provenance,
    )


def _pdp_table() -> TableRecord:
    provenance = VisualProvenance(page=6, object_id="tbl-1", object_type="table", origin="table_reported")
    grid = [
        ["Specimen", "Ecorr (V)", "Icorr (A/cm2)"],
        ["TE-GAE (1:1)", "-0.561", "3.413 × 10−6"],
        ["TE-GAE (2:1)", "-0.439", "7.480 × 10−7"],
    ]
    cells = [
        TableCell(
            row=row,
            column=column,
            cell_id=f"tbl-1-r{row}-c{column}",
            raw_text=value,
            provenance=VisualProvenance(
                page=6,
                object_id="tbl-1",
                object_type="table",
                origin="table_reported",
                row=row,
                column=column,
            ),
        )
        for row, values in enumerate(grid)
        for column, value in enumerate(values)
    ]
    return TableRecord(
        table_id="tbl-1",
        source_id="src-corrosion-test",
        page=6,
        table_number="1",
        caption="Polarization parameters",
        headers=[grid[0]],
        rows=grid[1:],
        cells=cells,
        raw_representation={"grid": grid},
        provenance=provenance,
    )


def test_corrosion_native_evidence_handles_pdf_nul_and_unicode_typography():
    bundle = _bundle(native_text="The EIS\x00measurement was performed from 10−2 to 105 Hz.")
    evidence = CorrosionEvidence(
        page=6,
        text_snippet="The EIS measurement was performed from 10−2 to 105 Hz.",
        source_type="text",
        original_source_type="native_text",
    )
    verified = verify_corrosion_evidence_item(evidence, bundle)
    assert verified.verbatim_match is True
    assert verified.page == 6
    assert verified.source_id == "src-corrosion-test"


def test_corrosion_table_evidence_verifies_exact_extracted_row():
    bundle = _bundle(tables=[_table()])
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-2",
        text_snippet="100 mmol·L-1 75.21",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, bundle)
    assert verified.verbatim_match is True
    assert verified.source_type == "table"
    assert verified.original_source_type == "table_reported"
    assert verified.page == 6
    assert verified.text_snippet == "100 mmol·L-1 75.21"


def test_corrosion_table_evidence_recovers_unique_row_column_synthesis_as_exact_row():
    bundle = _bundle(tables=[_table()])
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-2",
        text_snippet="Table 2: at 100 mmol·L-1 NaCl, Rs = 75.21 Ω·cm2.",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, bundle)
    assert verified.verbatim_match is True
    assert verified.text_snippet == "100 mmol·L-1 75.21"
    assert verified.locator == "tbl-2:r1:c1"


def test_corrosion_table_evidence_accepts_scientific_notation_typography_only_when_row_and_column_agree():
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-1",
        text_snippet="Table 1: TE-GAE (2:1); Icorr = 7.480e-7 A/cm2.",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, _bundle(tables=[_pdp_table()]))
    assert verified.verbatim_match is True
    assert verified.text_snippet == "TE-GAE (2:1) -0.439 7.480 × 10−7"
    assert verified.locator == "tbl-1:r2:c2"


def test_corrosion_table_evidence_rejects_value_from_different_treatment_row():
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-1",
        text_snippet="Table 1: TE-GAE (1:1); Icorr = 7.480e-7 A/cm2.",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, _bundle(tables=[_pdp_table()]))
    assert verified.verbatim_match is False


def test_corrosion_table_evidence_rejects_value_from_wrong_metric_column():
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-1",
        text_snippet="Table 1: TE-GAE (2:1); Ecorr = 7.480e-7 V.",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, _bundle(tables=[_pdp_table()]))
    assert verified.verbatim_match is False


def test_verified_metric_evidence_can_ground_experiment_shell_without_inventing_evidence():
    document = CorrosionDocument.model_validate({
        "source": {"title": "Example corrosion paper"},
        "materials": [{
            "local_id": "mat-1",
            "reported_name": "Alloy",
            "material_class": "alloy",
            "role": "working_electrode",
            "ownership": "focal_work",
            "evidence": [{
                "page": 6,
                "text_snippet": "Alloy",
                "source_type": "text",
                "original_source_type": "native_text",
            }],
        }],
        "experiments": [{
            "experiment_id": "exp-eis-100",
            "experiment_type": "eis",
            "material_refs": ["mat-1"],
            "ownership": "focal_work",
            "metrics": [{
                "property": "solution_resistance",
                "quantity": {"raw_value": "75.21 Ω·cm2", "value": 75.21, "unit": "Ω·cm2", "qualifier": "exact"},
                "ownership": "focal_work",
                "evidence": [{
                    "page": 6,
                    "table_id": "tbl-2",
                    "text_snippet": "100 mmol·L-1 75.21",
                    "source_type": "table",
                    "original_source_type": "table_reported",
                }],
            }],
        }],
    })
    bundle = _bundle(native_text="Alloy", tables=[_table()])
    verified = verify_corrosion_document_evidence(document, bundle)

    metric_evidence = verified.experiments[0].metrics[0].evidence[0]
    assert metric_evidence.verbatim_match is True
    assert metric_evidence.original_source_type == "table_reported"
    assert len(verified.experiments[0].evidence) == 1
    record_evidence = verified.experiments[0].evidence[0]
    assert record_evidence.text_snippet == metric_evidence.text_snippet
    assert record_evidence.verbatim_match is True
    assert record_evidence.table_id == "tbl-2"


def test_unverified_child_evidence_does_not_ground_experiment_shell():
    document = CorrosionDocument.model_validate({
        "source": {"title": "Example corrosion paper"},
        "materials": [{
            "local_id": "mat-1",
            "reported_name": "Alloy",
            "material_class": "alloy",
            "role": "working_electrode",
            "ownership": "focal_work",
        }],
        "experiments": [{
            "experiment_id": "exp-eis-100",
            "experiment_type": "eis",
            "material_refs": ["mat-1"],
            "ownership": "focal_work",
            "metrics": [{
                "property": "solution_resistance",
                "quantity": {"raw_value": "75.21 Ω·cm2", "value": 75.21, "unit": "Ω·cm2", "qualifier": "exact"},
                "ownership": "focal_work",
                "evidence": [{
                    "page": 6,
                    "table_id": "tbl-2",
                    "text_snippet": "not an exact table row",
                    "source_type": "table",
                    "original_source_type": "table_reported",
                }],
            }],
        }],
    })
    verified = verify_corrosion_document_evidence(document, _bundle(tables=[_table()]))
    assert verified.experiments[0].metrics[0].evidence[0].verbatim_match is False
    assert verified.experiments[0].evidence == []
