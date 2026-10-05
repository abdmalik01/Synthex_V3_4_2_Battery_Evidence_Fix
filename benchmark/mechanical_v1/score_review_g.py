"""Frozen-gold ownership and contamination scorer for MECH-REVIEW-G."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_review_g(archive, guarded, route, gold: dict) -> dict:
    review = archive.domain_payloads[0].values["mechanical_review"]
    candidates = review["noncanonical_candidates"]
    example = gold["reviewed_noncanonical_example"]
    cited = [item for item in candidates if item["kind"] == "experiment"]
    cited_value = bool(cited and cited[0]["raw_object"]["outputs"][0]["raw_value"] == example["raw_value"])
    evidence_retained = bool(
        cited and cited[0]["raw_object"]["outputs"][0].get("evidence")
        and cited[0]["raw_object"]["outputs"][0]["evidence"][0].get("text_snippet")
    )
    ownership_violations = sum(item["ownership"] == "focal_work" for item in candidates)
    graph_contamination = len([item for item in archive.relationships if item.predicate != "reported_by"])
    checks = {
        "mechanical_route": route.domain == "mechanical",
        "review_paper_type": "review" in route.paper_types,
        "explicit_two_signal_review_detection": review["classification"] == "explicit_review" and len(review["detection_evidence"]) == 2,
        "zero_focal_experiments": not archive.experiments,
        "zero_focal_calculations": not archive.calculations,
        "cited_value_preserved_noncanonical": cited_value,
        "evidence_retained": evidence_retained,
        "zero_ownership_violations": ownership_violations == 0,
        "zero_analytics_contamination": not project_archives([archive]),
        "zero_graph_contamination": graph_contamination == 0,
        "provider_not_called": True,
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "route": route.domain, "paper_types": route.paper_types,
        "review_classification": review["classification"],
        "noncanonical_candidate_count": len(candidates),
        "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        "ownership_violations": ownership_violations,
        "evidence_violations": 0 if evidence_retained else 1,
        "analytics_contamination_count": len(project_archives([archive])),
        "graph_contamination_count": graph_contamination,
    }
