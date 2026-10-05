"""Conservative whole-document ownership containment for Membranes reviews."""

from __future__ import annotations

from copy import deepcopy
import re

from .draft_models import ExtractedDocument
from .source_context import SourceBundle


_SELF_DESCRIPTION = re.compile(
    r"(?:this review addresses|discussed in this review|this review (?:focuses|summarizes|examines)|in this review)",
    re.IGNORECASE,
)


def membranes_review_evidence(bundle: SourceBundle) -> list[dict]:
    """Return evidence only from the first four publisher pages."""
    first_pages = bundle.pages[:4]
    label = next(
        (
            (page.page, line.strip())
            for page in first_pages
            for line in page.native_text.splitlines()
            if line.strip().casefold() == "review"
        ),
        None,
    )
    description = next(
        (
            (page.page, match.group(0))
            for page in first_pages
            if (match := _SELF_DESCRIPTION.search(page.native_text))
        ),
        None,
    )
    evidence = []
    if label:
        evidence.append({"kind": "publisher_article_type", "page": label[0], "text_snippet": label[1]})
    if description:
        evidence.append({"kind": "author_self_description", "page": description[0], "text_snippet": description[1]})
    return evidence


def is_explicit_pure_membranes_review(bundle: SourceBundle) -> bool:
    return {item["kind"] for item in membranes_review_evidence(bundle)} == {
        "publisher_article_type", "author_self_description",
    }


def _candidate(kind: str, item) -> dict:
    return {
        "kind": kind,
        "local_id": item.local_id,
        "ownership": item.ownership,
        "raw_object": item.model_dump(mode="json", exclude_none=True),
    }


def apply_membranes_review_ownership_guard(
    document: ExtractedDocument,
    source_bundle: SourceBundle,
) -> ExtractedDocument:
    """Make scientific candidates non-focal only after dual-signal detection."""
    guarded = document.model_copy(deep=True)
    if not is_explicit_pure_membranes_review(source_bundle):
        return guarded

    for collection in (
        guarded.materials, guarded.devices, guarded.processes,
        guarded.experiments, guarded.calculations,
    ):
        for item in collection:
            if item.ownership in {"focal_work", "unknown"}:
                item.ownership = "review_summary"

    candidates = [
        *(_candidate("material", item) for item in guarded.materials),
        *(_candidate("device", item) for item in guarded.devices),
        *(_candidate("process", item) for item in guarded.processes),
        *(_candidate("experiment", item) for item in guarded.experiments),
        *(_candidate("calculation", item) for item in guarded.calculations),
    ]
    values = deepcopy(guarded.domain_values)
    values["membranes_review"] = {
        "classification": "explicit_review",
        "detection_evidence": membranes_review_evidence(source_bundle),
        "noncanonical_candidates": candidates,
    }
    guarded.domain_values = values
    note = "review_ownership_guard:explicit_pure_review_all_scientific_candidates_nonfocal"
    if note not in guarded.extraction_notes:
        guarded.extraction_notes.append(note)
    return ExtractedDocument.model_validate(guarded.model_dump(mode="python"))
