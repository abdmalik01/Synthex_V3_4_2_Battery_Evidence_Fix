"""Frozen-gold ownership and contamination scorer for AM-REVIEW-G."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_review_g(archive, guarded, route, gold: dict) -> dict:
    review = archive.domain_payloads[0].values["additive_manufacturing_review"]
    candidates = review["noncanonical_candidates"]
    example = gold["reviewed_noncanonical_example"]
    experiments = [item for item in candidates if item["kind"] == "experiment"]
    cited_value = bool(
        experiments
        and experiments[0]["raw_object"]["outputs"][0]["raw_value"] == example["raw_value"]
    )
    evidence_retained = bool(
        experiments
        and experiments[0]["raw_object"]["outputs"][0].get("evidence")
        and experiments[0]["raw_object"]["outputs"][0]["evidence"][0].get("text_snippet")
    )
    ownership_violations = sum(
        item["ownership"] not in {"cited_prior_work", "review_summary", "comparison_table"}
        for item in candidates
    )
    canonical_measurements = (
        [value for process in archive.processes for value in process.parameters]
        + [value for experiment in archive.experiments for value in experiment.outputs]
        + [value for calculation in archive.calculations for value in calculation.outputs]
    )
    scientific_graph = [item for item in archive.relationships if item.predicate != "reported_by"]
    analytics = project_archives([archive])
    checks = {
        "additive_manufacturing_route": route.domain == "additive_manufacturing",
        "review_paper_type": "review" in route.paper_types,
        "explicit_two_signal_review_detection": (
            review["classification"] == "explicit_review"
            and {item["kind"] for item in review["detection_evidence"]}
            == {"publisher_article_type", "author_self_description"}
        ),
        "zero_focal_experiments": not archive.experiments,
        "zero_focal_calculations": not archive.calculations,
        "zero_canonical_measurements": not canonical_measurements,
        "cited_value_preserved_noncanonical": cited_value,
        "evidence_retained": evidence_retained,
        "zero_ownership_violations": ownership_violations == 0,
        "zero_analytics_contamination": not analytics,
        "zero_graph_contamination": not scientific_graph,
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions),
        "assertions": assertions,
        "route": route.domain,
        "paper_types": route.paper_types,
        "review_classification": review["classification"],
        "noncanonical_candidate_count": len(candidates),
        "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations),
        "canonical_measurements": len(canonical_measurements),
        "ownership_violations": ownership_violations,
        "evidence_violations": 0 if evidence_retained else 1,
        "analytics_contamination_count": len(analytics),
        "graph_contamination_count": len(scientific_graph),
    }
