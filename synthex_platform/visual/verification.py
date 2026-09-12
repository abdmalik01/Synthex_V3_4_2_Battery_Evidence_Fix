"""Deterministic visual-cell evidence verification, independent of Batteries V1."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from .models import VisualDocument, VisualProvenance


class VerificationResult(BaseModel):
    verified: bool
    verification_status: str
    evidence_strength: str
    match_type: str | None = None
    reason: str | None = None


def _normalized(value: str) -> str:
    # NFC is a lossless Unicode equivalence normalization; no scientific rewriting.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def classify_evidence_strength(provenance: VisualProvenance, verified: bool) -> str:
    if not verified:
        return "unverified"
    if provenance.origin == "table_reported" and (provenance.parser_or_method or provenance.parser):
        return "verified_native"
    if provenance.origin == "ocr_extracted":
        return "verified_ocr"
    if provenance.origin == "figure_digitized":
        return "estimated_digitized"
    return "unverified"


def verify_table_evidence(document: VisualDocument, claim_text: str, evidence: VisualProvenance) -> VerificationResult:
    """Verify a claim against one explicitly located table cell; no fuzzy matching."""
    if evidence.origin != "table_reported":
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="unsupported_origin")
    if evidence.source_id and evidence.source_id != document.source_id:
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="source_mismatch")
    if not evidence.object_id:
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="missing_table_id")
    table = next((item for item in document.tables if item.table_id == evidence.object_id), None)
    if table is None:
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="table_not_found")
    if evidence.page != table.page:
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="page_mismatch")
    if evidence.cell_id:
        cell = next((item for item in table.cells if item.cell_id == evidence.cell_id), None)
    elif evidence.row is not None and evidence.column is not None:
        cell = next((item for item in table.cells if item.row == evidence.row and item.column == evidence.column), None)
    else:
        cell = None
    if cell is None:
        return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="cell_not_found")
    actual = cell.raw_text or ""
    if claim_text == actual:
        return VerificationResult(verified=True, verification_status="verified_source", evidence_strength=classify_evidence_strength(evidence, True), match_type="exact_raw")
    if _normalized(claim_text) == _normalized(actual):
        return VerificationResult(verified=True, verification_status="verified_source", evidence_strength=classify_evidence_strength(evidence, True), match_type="normalized_whitespace_or_unicode")
    return VerificationResult(verified=False, verification_status="rejected", evidence_strength="unverified", reason="cell_text_mismatch")
