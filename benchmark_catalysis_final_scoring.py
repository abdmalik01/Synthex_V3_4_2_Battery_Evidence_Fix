"""Remediation-aware scoring helpers for Catalysis Stage 3 final confirmation.

Historical Gold files remain untouched. Final confirmation uses the reviewed
Gold B remediation overlay because the paper does not explicitly establish a
geometric-area normalization basis merely by reporting mA cm-2 values and
providing electrode dimensions.
"""

from __future__ import annotations

import json
from typing import Any

from benchmark_catalysis_remediation import ADJUSTMENTS_PATH, load_remediation_gold
from benchmark_catalysis_scoring_v2 import metric_match, observed_metrics, score_metric_association


def gold_document(result: dict[str, Any]) -> dict[str, Any] | None:
    archive = result.get("archive") or {}
    for payload in archive.get("domain_payloads", []):
        if payload.get("domain") != "catalysis":
            continue
        values = payload.get("values") or {}
        document = values.get("validated_document")
        if isinstance(document, dict):
            return document
    return None


def normalization_source_review_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Check the two reviewed Gold B normalization expectations on typed v2 projections."""
    adjustments = json.loads(ADJUSTMENTS_PATH.read_text(encoding="utf-8"))["adjustments"]
    observed = observed_metrics(document)
    results = []
    for adjustment in adjustments:
        selector = adjustment["selector"]
        candidates = [item for item in observed if metric_match(selector, item)]
        matched = bool(candidates) and all(
            item.get("normalization_basis") in (None, "unknown") for item in candidates
        )
        results.append({
            "selector": selector,
            "expected": "unknown_or_absent",
            "observed": [item.get("normalization_basis") for item in candidates],
            "matched": matched,
        })
    return {
        "expected_count": len(results),
        "matched_count": sum(item["matched"] for item in results),
        "results": results,
        "gold_adjustment": str(ADJUSTMENTS_PATH),
    }


def evaluate_gold_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a saved Gold paper with the scientifically reviewed final contract."""
    benchmark_id = result.get("benchmark_id")
    if benchmark_id not in {"CAT-GOLD-A", "CAT-GOLD-B"}:
        return None
    document = gold_document(result)
    if document is None:
        return None

    gold = load_remediation_gold()[benchmark_id]
    evaluation: dict[str, Any] = {
        "metric_association_v2": score_metric_association(gold, document),
    }
    if benchmark_id == "CAT-GOLD-B":
        evaluation["normalization_source_review"] = normalization_source_review_v2(document)
    return evaluation


def evaluation_complete(evaluation: dict[str, Any] | None) -> bool:
    if evaluation is None:
        return True
    metric = evaluation.get("metric_association_v2") or {}
    if metric.get("matched_count") != metric.get("expected_count"):
        return False
    normalization = evaluation.get("normalization_source_review")
    if normalization is not None:
        if normalization.get("matched_count") != normalization.get("expected_count"):
            return False
    return True
