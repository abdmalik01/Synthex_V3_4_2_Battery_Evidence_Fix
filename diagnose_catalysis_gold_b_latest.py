"""Diagnose the latest saved CAT-GOLD-B result without external calls.

Prints the validated electrocatalysis experiments exactly as saved, the scoring-v2
projection, and field-by-field mismatches against the remediation-aware Gold B
contract. This is diagnostic only: it does not alter extraction, Gold, or scoring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_final_scoring import evaluate_gold_result, gold_document
from benchmark_catalysis_remediation import load_remediation_gold
from benchmark_catalysis_scoring_v2 import (
    _ASSOCIATION_FIELDS,
    _equal,
    _field_value,
    _reported_name_equal,
    metric_match,
    observed_metrics,
    reaction_equal,
    unit_equal,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"


def _latest_gold_b_result() -> Path:
    candidates = sorted(
        OUTPUT_ROOT.glob("stage3_final_resume_*/cat-gold-b/cat-gold-b_result.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No saved CAT-GOLD-B resume result found.")
    return candidates[0]


def _mismatches(expected: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for field in ("property", "value"):
        ev = expected.get(field)
        if ev is not None and not _equal(ev, observed.get(field)):
            problems.append(f"{field}: expected={ev!r} observed={observed.get(field)!r}")
    ep = _field_value(expected, "product")
    op = _field_value(observed, "product")
    if expected.get("unit") is not None and not unit_equal(
        expected.get("unit"), observed.get("unit"),
        expected_product=ep, observed_product=op,
    ):
        problems.append(f"unit: expected={expected.get('unit')!r} observed={observed.get('unit')!r}")
    if expected.get("qualifier") is not None and not _equal(expected.get("qualifier"), observed.get("qualifier")):
        problems.append(
            f"qualifier: expected={expected.get('qualifier')!r} observed={observed.get('qualifier')!r}"
        )
    for field in _ASSOCIATION_FIELDS:
        ev = _field_value(expected, field)
        if ev is None:
            continue
        ov = _field_value(observed, field)
        if ov is None:
            problems.append(f"{field}: expected={ev!r} observed=None")
            continue
        if field == "catalyst":
            ok = _reported_name_equal(ev, ov)
        elif field == "reaction":
            ok = reaction_equal(ev, ov)
        else:
            ok = _equal(ev, ov)
        if not ok:
            problems.append(f"{field}: expected={ev!r} observed={ov!r}")
    return problems


def main() -> None:
    result_path = _latest_gold_b_result()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    document = gold_document(result)
    if document is None:
        raise RuntimeError("Saved result has no validated Catalysis document.")

    gold = load_remediation_gold()["CAT-GOLD-B"]
    projected = observed_metrics(document)
    evaluation = evaluate_gold_result(result) or {}

    print("\n=== GOLD B ZERO-CALL DIAGNOSTIC ===")
    print("Result:", result_path)
    print("External calls: 0")
    print("Extraction status:", result.get("extraction_status"))
    experiments = document.get("electrocatalysis_experiments", [])
    print("Electrocatalysis experiments:", len(experiments))

    for index, experiment in enumerate(experiments, 1):
        print(f"\nEXPERIMENT {index}")
        for key in (
            "local_id", "catalyst_ref", "reaction", "reaction_class", "reported_reaction",
            "feed_composition", "electrolyte", "pH", "reference_electrode",
        ):
            if key in experiment:
                print(f"  {key}: {json.dumps(experiment.get(key), ensure_ascii=False)}")
        metrics = experiment.get("metrics", [])
        print("  metrics:", len(metrics))
        for metric in metrics:
            print("   -", json.dumps(metric, ensure_ascii=False))

    print("\nSCORING-V2 PROJECTED METRICS:", len(projected))
    for index, item in enumerate(projected, 1):
        print(f"  [{index}]", json.dumps(item, ensure_ascii=False))

    print("\nGOLD EXPECTATIONS AND CLOSEST MISMATCHES")
    for expected in gold.get("metrics", []):
        print("\nEXPECTED |", json.dumps(expected, ensure_ascii=False))
        if any(metric_match(expected, candidate) for candidate in projected):
            print("  MATCHED")
            continue
        ranked = sorted(
            ((_mismatches(expected, candidate), candidate) for candidate in projected),
            key=lambda pair: len(pair[0]),
        )
        if not ranked:
            print("  NO OBSERVED METRICS")
            continue
        for rank, (problems, candidate) in enumerate(ranked[:3], 1):
            print(f"  CANDIDATE {rank} mismatches={len(problems)}")
            for problem in problems:
                print("   -", problem)
            print("   ", json.dumps(candidate, ensure_ascii=False))

    metric = evaluation.get("metric_association_v2") or {}
    normalization = evaluation.get("normalization_source_review") or {}
    print("\nSUMMARY")
    print("Metric association:", f"{metric.get('matched_count')}/{metric.get('expected_count')}")
    print(
        "Normalization source review:",
        f"{normalization.get('matched_count')}/{normalization.get('expected_count')}",
    )


if __name__ == "__main__":
    main()
