from __future__ import annotations

from synthex_platform.extraction.corrosion_evidence import verify_corrosion_evidence_item
from synthex_platform.extraction.corrosion_models import CorrosionEvidence
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


def test_corrosion_table_evidence_does_not_accept_synthesized_sentence():
    bundle = _bundle(tables=[_table()])
    evidence = CorrosionEvidence(
        page=6,
        table_id="tbl-2",
        text_snippet="Table 2: at 100 mmol·L-1 NaCl, Rs = 75.21 Ω·cm2.",
        source_type="table",
        original_source_type="table_reported",
    )
    verified = verify_corrosion_evidence_item(evidence, bundle)
    assert verified.verbatim_match is False
