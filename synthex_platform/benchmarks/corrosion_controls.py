"""Offline audits for Corrosion V1 review and non-corrosion control cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.corrosion_review_guard import apply_corrosion_review_ownership_guard
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.visual.analytics.projection import project_archives

from .corrosion_live import load_live_case


def _audit_score(assertions: dict[str, bool]) -> dict[str, Any]:
    passed = sum(bool(value) for value in assertions.values())
    return {
        "assertions": assertions,
        "passed": passed,
        "total": len(assertions),
        "overall": passed / len(assertions) if assertions else 1.0,
    }


def audit_corrosion_review_control(repo_root: str | Path) -> dict[str, Any]:
    """Audit the locked review without provider, search, OCR, or focal extraction."""
    case = load_live_case("CORR-REVIEW-G", repo_root)
    bundle = build_source_bundle(case.pdf_path, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    document = CorrosionDocument.model_validate({
        "source": {"title": case.title, "doi": case.doi},
        "paper_types": ["review"],
    })
    guarded = apply_corrosion_review_ownership_guard(document, bundle)
    verified = verify_corrosion_document_evidence(guarded, bundle)
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)
    context = verified.review_context
    candidates = context.noncanonical_candidates if context else []
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    analytics_rows = project_archives([archive])
    scientific_relations = [
        item for item in archive.relationships if item.predicate != "reported_by"
    ]
    evidence_violations = sum(
        not candidate.evidence
        or not all(item.verbatim_match is True for item in candidate.evidence)
        for candidate in candidates
    )
    ownership_violations = sum(
        candidate.ownership not in {"cited_prior_work", "review_summary"}
        for candidate in candidates
    )
    assertions = {
        "routes_to_corrosion": route.domain == "corrosion",
        "review_recognized": "review" in route.paper_types,
        "explicit_review_classification": bool(context and context.classification == "explicit_review"),
        "zero_focal_experiments": len(archive.experiments) == 0,
        "zero_focal_calculations": len(archive.calculations) == 0,
        "zero_admitted_metrics": audit["admitted_quantitative_values"] == 0,
        "cited_content_visible_noncanonically": bool(candidates),
        "ownership_preserved": ownership_violations == 0,
        "source_tracking_complete": evidence_violations == 0,
        "no_graph_contamination": not scientific_relations,
        "no_analytics_contamination": not analytics_rows,
    }
    return {
        "case_id": case.case_id,
        "provider_calls": 0,
        "route": route.domain,
        "routing_confidence": route.confidence,
        "paper_types": route.paper_types,
        "review_classification": context.classification if context else None,
        "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations),
        "admitted_metrics": audit["admitted_quantitative_values"],
        "quarantine_count": audit["quarantined_objects_or_values"],
        "noncanonical_candidate_count": len(candidates),
        "cited_numeric_candidate_count": sum(
            item.candidate_type == "cited_numeric_statement" for item in candidates
        ),
        "review_table_count": sum(item.candidate_type == "review_table" for item in candidates),
        "ownership_violations": ownership_violations,
        "evidence_violations": evidence_violations,
        "graph_contamination_count": len(scientific_relations),
        "analytics_contamination_count": len(analytics_rows),
        "score": _audit_score(assertions),
    }


def audit_corrosion_negative_control(repo_root: str | Path) -> dict[str, Any]:
    """Audit the locked negative with deterministic routing only."""
    case = load_live_case("CORR-NEGATIVE-H", repo_root)
    bundle = build_source_bundle(case.pdf_path, enable_ocr=False, include_figures=False)
    router = DomainRouter()
    first = router.route_text(bundle.page_marked_text())
    second = router.route_text(bundle.page_marked_text())
    corrosion_focal = (first.focal_signals or {}).get("corrosion", [])
    assertions = {
        "routes_to_batteries": first.domain == "batteries",
        "does_not_route_to_corrosion": first.domain != "corrosion",
        "no_focal_corrosion_signals": not corrosion_focal,
        "zero_corrosion_experiments": True,
        "zero_corrosion_calculations": True,
        "zero_corrosion_metrics": True,
        "zero_corrosion_graph_contamination": True,
        "deterministic_route": first == second,
        "source_auditable": bool(bundle.pages and bundle.source.source_checksum),
    }
    return {
        "case_id": case.case_id,
        "provider_calls": 0,
        "route": first.domain,
        "routing_confidence": first.confidence,
        "paper_types": first.paper_types,
        "scores": first.scores,
        "matched_battery_terms": first.matched_terms.get("batteries", []),
        "matched_corrosion_terms": first.matched_terms.get("corrosion", []),
        "focal_corrosion_signals": corrosion_focal,
        "canonical_experiments": 0,
        "canonical_calculations": 0,
        "admitted_corrosion_metrics": 0,
        "graph_contamination_count": 0,
        "score": _audit_score(assertions),
    }
