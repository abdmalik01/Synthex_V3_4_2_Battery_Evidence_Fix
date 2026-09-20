"""Deterministic ownership containment for explicitly labelled corrosion reviews."""

from __future__ import annotations

import re

from synthex_platform.core.identifiers import stable_id

from .corrosion_models import (
    CorrosionDocument,
    CorrosionEvidence,
    CorrosionReviewCandidate,
    CorrosionReviewContext,
)
from .source_context import SourceBundle


_REFERENCE = re.compile(r"\[\s*\d[\d,\-\s]*\]")
_NUMERIC_UNIT = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|ppm|m?v\b|h\b|days?\b|years?\b|wt\.?\s*%|"
    r"[µμu]?m\b)|order\s+of\s+magnitude)",
    re.IGNORECASE,
)
_CORROSION_CONTEXT = re.compile(
    r"corrosion|coating|impedance|resistance|potential|salt[- ]spray|nacl|inhibitor|"
    r"delamination|self[- ]healing",
    re.IGNORECASE,
)


def _exact_review_evidence(bundle: SourceBundle) -> list[CorrosionEvidence]:
    if not bundle.pages:
        return []
    page = bundle.pages[0]
    evidence: list[CorrosionEvidence] = []
    review_line = next(
        (line.strip() for line in page.native_text.splitlines() if line.strip().casefold() == "review"),
        None,
    )
    if review_line:
        evidence.append(CorrosionEvidence(page=page.page, text_snippet=review_line, source_type="text"))
    summary = re.search(r"This review\s+summarizes.*?\.", page.native_text, re.IGNORECASE | re.DOTALL)
    if summary:
        evidence.append(CorrosionEvidence(
            page=page.page,
            text_snippet=summary.group(0),
            source_type="text",
        ))
    return evidence


def is_explicit_pure_review(bundle: SourceBundle) -> bool:
    """Require publisher/article labelling and author self-description."""
    return len(_exact_review_evidence(bundle)) >= 2


def _review_candidates(bundle: SourceBundle) -> list[CorrosionReviewCandidate]:
    candidates: list[CorrosionReviewCandidate] = []
    seen: set[str] = set()
    for page in bundle.pages:
        for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", page.native_text)):
            snippet = sentence.strip()
            if not snippet or not _REFERENCE.search(snippet):
                continue
            if not _NUMERIC_UNIT.search(snippet) or not _CORROSION_CONTEXT.search(snippet):
                continue
            token = re.sub(r"\s+", " ", snippet).casefold()
            if token in seen:
                continue
            seen.add(token)
            candidates.append(CorrosionReviewCandidate(
                candidate_id=stable_id("review", bundle.source.source_id, page.page, index, token),
                candidate_type="cited_numeric_statement",
                raw_text=snippet,
                ownership="cited_prior_work",
                evidence=[CorrosionEvidence(
                    page=page.page,
                    text_snippet=snippet,
                    source_type="text",
                )],
            ))
    for table in bundle.tables:
        caption = (table.caption or "").strip()
        if not caption:
            continue
        candidates.append(CorrosionReviewCandidate(
            candidate_id=stable_id("review", bundle.source.source_id, table.table_id),
            candidate_type="review_table",
            raw_text=caption,
            ownership="review_summary",
            evidence=[CorrosionEvidence(
                page=table.page,
                text_snippet=caption,
                source_type="table",
                original_source_type="table_reported",
                table_id=table.table_id,
            )],
        ))
    return candidates


def apply_corrosion_review_ownership_guard(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Contain every candidate from a publisher-labelled pure review as non-focal.

    Review-like introductions and mixed original papers do not activate this whole-
    document guard unless the source explicitly labels and describes itself as a review.
    """
    guarded = document.model_copy(deep=True)
    if not is_explicit_pure_review(source_bundle):
        return guarded

    if "review" not in guarded.paper_types:
        guarded.paper_types.append("review")
    for material in guarded.materials:
        if material.ownership in {"focal_work", "unknown"}:
            material.ownership = "review_summary"
    for preparation in guarded.surface_preparations:
        if preparation.ownership in {"focal_work", "unknown"}:
            preparation.ownership = "review_summary"
    for treatment in guarded.treatments:
        if treatment.ownership in {"focal_work", "unknown"}:
            treatment.ownership = "review_summary"
    for experiment in guarded.experiments:
        if experiment.ownership in {"focal_work", "unknown"}:
            experiment.ownership = "review_summary"
        for metric in experiment.metrics:
            if metric.ownership in {"focal_work", "unknown"}:
                metric.ownership = "review_summary"
    for calculation in guarded.calculations:
        if calculation.ownership in {"focal_work", "unknown"}:
            calculation.ownership = "review_summary"
        for output in calculation.outputs:
            if output.ownership in {"focal_work", "unknown"}:
                output.ownership = "review_summary"

    guarded.review_context = CorrosionReviewContext(
        classification="explicit_review",
        evidence=_exact_review_evidence(source_bundle),
        noncanonical_candidates=_review_candidates(source_bundle),
    )
    note = "review_ownership_guard:explicit_pure_review_all_scientific_candidates_nonfocal"
    if note not in guarded.extraction_notes:
        guarded.extraction_notes.append(note)
    return CorrosionDocument.model_validate(guarded.model_dump(mode="python"))
