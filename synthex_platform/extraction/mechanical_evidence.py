"""Verify Mechanical evidence against a locked source bundle before admission."""

from __future__ import annotations

from synthex_platform.core.models import Evidence
from .battery_evidence import normalize_evidence_text
from .draft_models import ExtractedDocument
from .source_context import SourceBundle


def _verified_evidence(item: Evidence, bundle: SourceBundle) -> Evidence:
    snippet = normalize_evidence_text(item.text_snippet or "")
    if not snippet or item.page is None or (item.source_id and item.source_id != bundle.source.source_id):
        return item.model_copy(update={"verbatim_match": False})
    page = next((page for page in bundle.pages if page.page == item.page), None)
    if page is None:
        return item.model_copy(update={"verbatim_match": False})
    if item.source_type.value == "table":
        table = next((table for table in bundle.tables if (
            table.table_id == item.table_id and table.page == item.page
        )), None)
        if table is None:
            matched = False
        else:
            grid = table.raw_representation.get("grid", [])
            matched = any(
                snippet in normalize_evidence_text(" ".join(str(cell or "") for cell in row))
                for row in grid
            )
    elif item.source_type.value == "text":
        source = page.text if page.origin == "ocr_extracted" else page.native_text
        matched = snippet in normalize_evidence_text(source)
    else:
        matched = False
    return item.model_copy(update={
        "source_id": bundle.source.source_id if matched else item.source_id,
        "verbatim_match": matched,
        "original_source_type": (
            "table_reported" if item.source_type.value == "table" else page.origin
        ) if matched else item.original_source_type,
    })


def verify_mechanical_document_evidence(draft: ExtractedDocument, bundle: SourceBundle) -> ExtractedDocument:
    """Return a deep copy; never accept the provider's own verbatim flag as verification."""
    verified = draft.model_copy(deep=True)
    for collection in (verified.materials, verified.processes, verified.experiments, verified.calculations):
        for record in collection:
            record.evidence = [_verified_evidence(item, bundle) for item in record.evidence]
            for field in ("parameters", "conditions", "outputs"):
                for measurement in getattr(record, field, []):
                    measurement.evidence = [_verified_evidence(item, bundle) for item in measurement.evidence]
    return verified
