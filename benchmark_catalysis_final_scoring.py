"""Remediation-aware scoring helpers for Catalysis Stage 3 final confirmation.

Historical Gold files remain untouched. Final confirmation must use the reviewed
Gold B remediation overlay because the paper does not explicitly establish a
geometric-area normalization basis merely by reporting mA cm-2 values and
providing electrode dimensions.
"""

from __future__ import annotations

from typing import Any

from benchmark_catalysis_remediation import load_remediation_gold, normalization_source_review
from benchmark_catalysis_scoring_v2 import score_metric_association


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
        evaluation["normalization_source_review"] = normalization_source_review(document)
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
