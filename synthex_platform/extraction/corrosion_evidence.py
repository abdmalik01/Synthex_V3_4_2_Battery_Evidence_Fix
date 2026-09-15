"""Evidence verification helpers for Corrosion V1.

Verification is deterministic and source-bundle backed. It makes no network or
LLM calls and never fabricates evidence when an exact source match is absent.
"""

from __future__ import annotations

import re

from .corrosion_models import CorrosionDocument, CorrosionEvidence
from .source_context import SourceBundle


def _normalize(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def verify_corrosion_evidence_item(
    evidence: CorrosionEvidence,
    source_bundle: SourceBundle,
) -> CorrosionEvidence:
    """Mark one evidence item verified only after one exact normalized page match."""
    snippet = (evidence.text_snippet or "").strip()
    if not snippet:
        return evidence.model_copy(update={"verbatim_match": False})

    needle = _normalize(snippet)
    matches = []
    for page in source_bundle.pages:
        source_text = page.text if page.origin == "ocr_extracted" else page.native_text
        if needle and needle in _normalize(source_text):
            matches.append(page)

    if len(matches) != 1:
        return evidence.model_copy(update={"verbatim_match": False})

    page = matches[0]
    if evidence.page is not None and evidence.page != page.page:
        return evidence.model_copy(update={"verbatim_match": False})

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
