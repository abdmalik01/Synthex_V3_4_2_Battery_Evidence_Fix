from synthex_platform.extraction.corrosion_evidence import verify_corrosion_evidence_item
from synthex_platform.extraction.corrosion_models import CorrosionEvidence
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


def _bundle() -> SourceBundle:
    page5 = (
        "Table 1. Electrochemical Test Results Obtained from Tafel Plots in Figure 6\n"
        "rusty steel plate −0.974 3.557 × 10−5 6.934 7.116\n"
        "TE-GAE (1:1) −0.561 3.413 × 10−6 10.408 5.134\n"
        "TE-GAE (2:1) −0.439 7.480 × 10−7 6.157 5.321\n"
    )
    return SourceBundle(
        source=SourceMetadata(source_id="src-b", filename="paper.pdf", source_checksum="abc"),
        pages=[
            SourcePageContext(
                page=5,
                native_text=page5,
                text=page5,
                native_parser="pymupdf",
                parser="pymupdf",
                origin="native_text",
                sufficient=True,
            ),
            SourcePageContext(
                page=6,
                native_text="unrelated page",
                text="unrelated page",
                native_parser="pymupdf",
                parser="pymupdf",
                origin="native_text",
                sufficient=True,
            ),
        ],
        tables=[],
    )


def test_human_table_label_verifies_exact_row_when_structured_table_is_missing():
    evidence = CorrosionEvidence(
        page=5,
        table_id="Table 1",
        text_snippet="TE-GAE (2:1) −0.439 7.480 × 10−7 6.157 5.321",
        source_type="table",
        original_source_type="native_text",
    )
    verified = verify_corrosion_evidence_item(evidence, _bundle())
    assert verified.verbatim_match is True
    assert verified.source_type == "table"
    assert verified.original_source_type == "native_text"
    assert verified.table_id == "Table 1"
    assert verified.locator == "Table 1"


def test_human_table_label_verifies_exact_caption_when_structured_table_is_missing():
    evidence = CorrosionEvidence(
        page=5,
        table_id="Table 1",
        text_snippet="Table 1. Electrochemical Test Results Obtained from Tafel Plots in Figure 6",
        source_type="table",
        original_source_type="native_text",
    )
    assert verify_corrosion_evidence_item(evidence, _bundle()).verbatim_match is True


def test_human_table_label_rejects_paraphrased_row():
    evidence = CorrosionEvidence(
        page=5,
        table_id="Table 1",
        text_snippet="TE-GAE 2:1 had Icorr 7.480e-7 A/cm2",
        source_type="table",
        original_source_type="native_text",
    )
    assert verify_corrosion_evidence_item(evidence, _bundle()).verbatim_match is False


def test_human_table_label_rejects_wrong_page():
    evidence = CorrosionEvidence(
        page=6,
        table_id="Table 1",
        text_snippet="TE-GAE (2:1) −0.439 7.480 × 10−7 6.157 5.321",
        source_type="table",
        original_source_type="native_text",
    )
    assert verify_corrosion_evidence_item(evidence, _bundle()).verbatim_match is False


def test_human_table_label_must_itself_exist_on_source_page():
    evidence = CorrosionEvidence(
        page=5,
        table_id="Table 99",
        text_snippet="TE-GAE (2:1) −0.439 7.480 × 10−7 6.157 5.321",
        source_type="table",
        original_source_type="native_text",
    )
    assert verify_corrosion_evidence_item(evidence, _bundle()).verbatim_match is False


def test_opaque_missing_parser_table_id_cannot_use_page_fallback():
    evidence = CorrosionEvidence(
        page=5,
        table_id="tbl-missing-deadbeef",
        text_snippet="TE-GAE (2:1) −0.439 7.480 × 10−7 6.157 5.321",
        source_type="table",
        original_source_type="native_text",
    )
    assert verify_corrosion_evidence_item(evidence, _bundle()).verbatim_match is False
