"""Frozen-gold routing and contamination scorer for AM-NEGATIVE-H."""

from __future__ import annotations

import re

from synthex_platform.visual.analytics.projection import project_archives


def score_negative_h(archive, first, second, text: str, gold: dict) -> dict:
    lowered = text.casefold()
    overlap = [
        term for term in gold["misleading_vocabulary"]
        if re.search(rf"\b{re.escape(term)}\w*\b", lowered)
    ]
    metrics = (
        [value for process in archive.processes for value in process.parameters]
        + [value for experiment in archive.experiments for value in experiment.outputs]
        + [value for calculation in archive.calculations for value in calculation.outputs]
    )
    analytics = project_archives([archive])
    graph = [item for item in archive.relationships if item.predicate != "reported_by"]
    repeat_same = (
        first.domain == second.domain
        and first.scores == second.scores
        and first.matched_terms == second.matched_terms
        and first.paper_types == second.paper_types
    )
    checks = {
        "source_is_primary_battery_study": (
            gold["source"]["true_domain"] == "batteries"
            and gold["source"]["article_type"] == "Article"
        ),
        "routes_to_batteries": first.domain == "batteries",
        "repeat_route_is_identical": repeat_same,
        "misleading_am_vocabulary_present": set(overlap) == set(gold["misleading_vocabulary"]),
        "no_focal_am_signals": not first.focal_signals.get("additive_manufacturing"),
        "zero_am_builds": not archive.processes,
        "zero_am_experiments": not archive.experiments,
        "zero_am_calculations": not archive.calculations,
        "zero_am_metrics": not metrics,
        "zero_graph_or_analytics_contamination": not graph and not analytics,
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "route": first.domain, "route_confidence": first.confidence,
        "scores": first.scores, "paper_types": first.paper_types,
        "misleading_vocabulary_detected": overlap,
        "matched_am_terms": first.matched_terms.get("additive_manufacturing", []),
        "focal_am_signals": first.focal_signals.get("additive_manufacturing", []),
        "canonical_builds": len(archive.processes),
        "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations),
        "canonical_metrics": len(metrics),
        "analytics_contamination_count": len(analytics),
        "graph_contamination_count": len(graph),
    }
