"""Deterministic provenance checks for Catalysis / Electrocatalysis V1."""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel

from .battery_evidence import marked_text_pages, normalize_evidence_text
from .catalysis_models import CatalysisDocument, CatalysisEvidence
from .source_context import SourceBundle


SUPPORTED_EVIDENCE_ORIGINS = frozenset(
    {
        "native_text",
        "table_reported",
        "figure_caption",
        "figure_annotation",
        "ocr_extracted",
        "figure_digitized",
    }
)


def normalize_catalysis_evidence_text(value: str) -> str:
    """Normalize Catalysis PDF text, including embedded-NUL parser separators.

    Some native scientific PDFs encode minus/superscript separators as NUL.
    Treating those bytes as spaces is a parser repair only; it does not alter
    scientific wording or broaden the Batteries evidence policy.
    """
    return normalize_evidence_text(value.replace("\x00", " "))


def _contains(candidate: str, snippet: str | None) -> bool:
    return bool(candidate and snippet) and normalize_catalysis_evidence_text(snippet) in normalize_catalysis_evidence_text(candidate)


def _table_candidate(bundle: SourceBundle, evidence: CatalysisEvidence) -> str:
    table = next((item for item in bundle.tables if item.table_id == evidence.table_id), None)
    if table is None:
        return ""
    # Quantitative table verification is deliberately cell-specific.
    cells = table.cells
    if evidence.cell_id:
        cells = [cell for cell in cells if cell.cell_id == evidence.cell_id]
    elif evidence.row is not None and evidence.column is not None:
        cells = [cell for cell in cells if cell.row == evidence.row and cell.column == evidence.column]
    elif evidence.locator:
        cells = [cell for cell in cells if cell.cell_id and cell.cell_id in evidence.locator]
    else:
        return ""
    return " ".join(cell.raw_text or "" for cell in cells)


def _figure_candidate(bundle: SourceBundle, evidence: CatalysisEvidence) -> str:
    figure = next((item for item in bundle.figures if item.figure_id == evidence.figure_id), None)
    if figure is None:
        return ""
    if evidence.original_source_type == "figure_caption":
        return figure.caption or ""
    return " ".join(str(item.model_dump(exclude_none=True)) for item in figure.annotations)


def verify_catalysis_evidence(
    evidence: CatalysisEvidence,
    source_text: str = "",
    source_bundle: SourceBundle | None = None,
) -> bool:
    """Set verification flags while preserving origin, snippet and locator."""
    origin = evidence.original_source_type
    if origin == "figure_digitized":
        evidence.estimated = True
        evidence.admission_status = "not_submitted"
        evidence.evidence_strength = "estimated_digitized"
        evidence.verbatim_match = False
        return False
    if origin not in SUPPORTED_EVIDENCE_ORIGINS or not evidence.text_snippet:
        evidence.evidence_strength = "unverified"
        evidence.verbatim_match = False
        return False

    if source_bundle is not None and origin == "table_reported":
        candidate = _table_candidate(source_bundle, evidence)
    elif source_bundle is not None and origin in {"figure_caption", "figure_annotation"}:
        candidate = _figure_candidate(source_bundle, evidence)
    elif source_bundle is not None and evidence.page is not None:
        page = next((page for page in source_bundle.pages if page.page == evidence.page), None)
        if page is None:
            candidate = ""
        elif origin == "ocr_extracted":
            candidate = page.text if page.origin == "ocr_extracted" else ""
        elif origin == "native_text":
            candidate = page.native_text
        else:
            candidate = page.text
    else:
        pages = marked_text_pages(source_text)
        candidate = pages.get(evidence.page, "") if evidence.page is not None and pages else source_text

    evidence.verbatim_match = _contains(candidate, evidence.text_snippet)
    evidence.evidence_strength = (
        "verified_ocr" if evidence.verbatim_match and origin == "ocr_extracted"
        else "verified_native" if evidence.verbatim_match
        else "unverified"
    )
    return bool(evidence.verbatim_match)


def evidence_is_value_specific(
    evidence: CatalysisEvidence,
    raw_value: str | None,
    value: float | None,
) -> bool:
    """Require the claimed value itself in a deterministically verified snippet."""
    if not evidence.verbatim_match or not evidence.text_snippet:
        return False
    snippet = normalize_catalysis_evidence_text(evidence.text_snippet)
    candidates = [raw_value, str(value) if value is not None else None]
    return any(candidate and normalize_catalysis_evidence_text(candidate) in snippet for candidate in candidates)


def _evidence_objects(value) -> Iterator[CatalysisEvidence]:
    if isinstance(value, CatalysisEvidence):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _evidence_objects(getattr(value, name))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _evidence_objects(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _evidence_objects(item)


def verify_catalysis_document_evidence(
    document: CatalysisDocument,
    source_text: str = "",
    source_bundle: SourceBundle | None = None,
) -> CatalysisDocument:
    for evidence in _evidence_objects(document):
        verify_catalysis_evidence(evidence, source_text, source_bundle)
    return document
