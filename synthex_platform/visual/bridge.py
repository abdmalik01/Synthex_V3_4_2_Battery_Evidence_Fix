"""Non-mutating adapters from verified visual locators to existing core evidence."""

from __future__ import annotations

from pydantic import BaseModel

from synthex_platform.core.models import Evidence, SourceType
from .models import VisualProvenance
from .verification import VerificationResult


def to_core_evidence(provenance: VisualProvenance, result: VerificationResult) -> Evidence:
    """Create compatible evidence only after a visual source verification succeeds."""
    if not result.verified:
        raise ValueError("Unverified visual evidence cannot be bridged to core evidence.")
    return Evidence(
        source_id=provenance.source_id, page=provenance.page, source_type=SourceType.table,
        text_snippet=provenance.raw_text, table_id=provenance.object_id,
        locator=f"row={provenance.row};column={provenance.column};cell_id={provenance.cell_id}",
        verbatim_match=True, confidence=provenance.confidence,
    )


def with_visual_evidence(record: BaseModel, provenance: VisualProvenance, result: VerificationResult) -> BaseModel:
    """Return a copy of a Measurement/Experiment/Calculation; never mutate input."""
    if not hasattr(record, "evidence"):
        raise TypeError("Record must expose an evidence list.")
    return record.model_copy(update={"evidence": [*record.evidence, to_core_evidence(provenance, result)]})
