"""Evidence verification helpers for Corrosion V1.

Verification is deterministic and source-bundle backed. It makes no network or
LLM calls and never fabricates evidence when an exact source match is absent.
"""

from __future__ import annotations

from collections import defaultdict

from .battery_evidence import normalize_evidence_text
from .corrosion_models import CorrosionDocument, CorrosionEvidence
from .source_context import SourceBundle


def _normalize(text: str) -> str:
    """Normalize parser typography without turning paraphrases into matches.

    Scientific PDFs can contain embedded NUL separators, compatibility glyphs,
    non-breaking spaces, Unicode minus signs, and line-break hyphenation. Reuse the
    conservative Batteries normalizer and treat NUL only as parser whitespace.
    """
    return normalize_evidence_text((text or "").replace("\x00", " "))


def _page_text(page) -> str:
    return page.text if page.origin == "ocr_extracted" else page.native_text


def _matching_text_pages(snippet: str, source_bundle: SourceBundle, page_number: int | None) -> list:
    needle = _normalize(snippet)
    if not needle:
        return []
    pages = source_bundle.pages
    if page_number is not None:
        pages = [page for page in pages if page.page == page_number]
    return [page for page in pages if needle in _normalize(_page_text(page))]


def _table_candidates(table) -> list[str]:
    """Return exact table-derived candidate strings without scientific rewriting."""
    candidates: list[str] = []
    if table.caption:
        candidates.append(table.caption)

    by_row: dict[int, list] = defaultdict(list)
    for cell in table.cells:
        by_row[cell.row].append(cell)
        if cell.raw_text:
            candidates.append(cell.raw_text)
    for row in sorted(by_row):
        joined = " ".join(
            str(cell.raw_text or "")
            for cell in sorted(by_row[row], key=lambda item: item.column)
            if cell.raw_text
        ).strip()
        if joined:
            candidates.append(joined)

    grid = table.raw_representation.get("grid", []) if isinstance(table.raw_representation, dict) else []
    for row in grid:
        if isinstance(row, list):
            joined = " ".join(str(value or "") for value in row if value not in (None, "")).strip()
            if joined:
                candidates.append(joined)

    # De-duplicate equivalent parser renderings so one source row is not counted twice.
    unique: dict[str, str] = {}
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized:
            unique.setdefault(normalized, candidate)
    return list(unique.values())


def _matching_table_candidates(evidence: CorrosionEvidence, source_bundle: SourceBundle) -> tuple[object | None, list[str]]:
    if not evidence.table_id:
        return None, []
    table = next((item for item in source_bundle.tables if item.table_id == evidence.table_id), None)
    if table is None:
        return None, []
    if evidence.page is not None and evidence.page != table.page:
        return table, []
    needle = _normalize(evidence.text_snippet or "")
    matches = [candidate for candidate in _table_candidates(table) if needle and needle in _normalize(candidate)]
    return table, matches


def verify_corrosion_evidence_item(
    evidence: CorrosionEvidence,
    source_bundle: SourceBundle,
) -> CorrosionEvidence:
    """Verify one evidence item against exact source-backed text or table content.

    Table evidence is verified only when it names a real ``table_id`` and its snippet
    is an exact normalized substring of one unique extracted table cell/row/caption.
    Otherwise verification falls back to exact normalized page-text matching.
    """
    snippet = (evidence.text_snippet or "").strip()
    if not snippet:
        return evidence.model_copy(update={"verbatim_match": False})

    if evidence.table_id:
        table, matches = _matching_table_candidates(evidence, source_bundle)
        if table is None or len(matches) != 1:
            return evidence.model_copy(update={"verbatim_match": False})
        return evidence.model_copy(update={
            "source_id": source_bundle.source.source_id,
            "page": table.page,
            "source_type": "table",
            "original_source_type": "table_reported",
            "verbatim_match": True,
        })

    matches = _matching_text_pages(snippet, source_bundle, evidence.page)
    if len(matches) != 1:
        return evidence.model_copy(update={"verbatim_match": False})

    page = matches[0]
    return evidence.model_copy(update={
        "source_id": source_bundle.source.source_id,
        "page": page.page,
        "source_type": "text" if evidence.source_type == "unknown" else evidence.source_type,
        "original_source_type": page.origin,
        "verbatim_match": True,
    })


def verify_corrosion_document_evidence(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Verify all Corrosion V1 evidence leaves while preserving scientific content."""
    payload = document.model_dump(mode="python")

    def walk(value):
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "text_snippet" in value and set(value).issubset(set(CorrosionEvidence.model_fields)):
            item = CorrosionEvidence.model_validate(value)
            return verify_corrosion_evidence_item(item, source_bundle).model_dump(mode="python")
        return {key: walk(item) for key, item in value.items()}

    return CorrosionDocument.model_validate(walk(payload))
