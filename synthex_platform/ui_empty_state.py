from __future__ import annotations

from typing import Any


def _payload_values(archive: Any, domain: str) -> dict[str, Any]:
    payloads = getattr(archive, "domain_payloads", None) or []
    for payload in payloads:
        payload_domain = getattr(payload, "domain", None)
        if payload_domain is None and isinstance(payload, dict):
            payload_domain = payload.get("domain")
        if payload_domain != domain:
            continue
        values = getattr(payload, "values", None)
        if values is None and isinstance(payload, dict):
            values = payload.get("values")
        if isinstance(values, dict):
            return values
    return {}


def archive_empty_state(archive: Any, *, result_count: int) -> dict[str, Any] | None:
    """Return a researcher-facing explanation when an archive has no result rows.

    This is presentation-only. It does not alter extraction, ownership,
    admission, quarantine, or canonical archive records.
    """
    if result_count:
        return None

    domain = getattr(getattr(archive, "metadata", None), "domain", None)
    values = _payload_values(archive, domain) if domain else {}
    document = values.get("validated_document") if isinstance(values, dict) else None
    document = document if isinstance(document, dict) else {}

    paper_types = [str(item).casefold() for item in document.get("paper_types", [])]
    notes = [str(item) for item in (document.get("extraction_notes") or values.get("extraction_notes") or [])]
    audit = values.get("admissibility_audit") if isinstance(values.get("admissibility_audit"), dict) else {}
    admitted = int(audit.get("canonical_admission_count", audit.get("admitted_quantitative_values", 0)) or 0)
    quarantined = int(audit.get("quarantined_objects_or_values", 0) or 0)

    if "review" in paper_types:
        return {
            "kind": "review_no_focal_data",
            "title": "No focal scientific results extracted",
            "message": (
                "This paper was classified as a review article. Synthex found no original focal "
                "experimental or computational dataset eligible for canonical results. Numerical "
                "values belonging to cited literature are intentionally not presented as this paper's own results."
            ),
            "details": notes,
            "admitted": admitted,
            "quarantined": quarantined,
        }

    if admitted == 0 and quarantined > 0:
        return {
            "kind": "quarantined_only",
            "title": "No canonical results admitted",
            "message": (
                "Synthex extracted candidate scientific records, but none passed the current evidence, "
                "ownership, or scientific-admission rules. Enable ‘Include quarantined’ to review them."
            ),
            "details": notes,
            "admitted": admitted,
            "quarantined": quarantined,
        }

    return {
        "kind": "no_structured_results",
        "title": "No structured results available",
        "message": (
            "The extraction completed, but this archive contains no result observations to display. "
            "This can happen when a paper contains no focal value-specific dataset for the selected domain."
        ),
        "details": notes,
        "admitted": admitted,
        "quarantined": quarantined,
    }
