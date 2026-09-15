"""Re-evaluate the latest saved Gold B result with zero external calls."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark_catalysis_final_scoring import evaluate_gold_result, evaluation_complete


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"


def _latest_gold_b_result() -> Path:
    candidates = []
    for run in OUTPUT_ROOT.glob("stage3_final_resume_*"):
        path = run / "cat-gold-b" / "cat-gold-b_result.json"
        if path.exists():
            candidates.append(path)
    for run in OUTPUT_ROOT.glob("stage3_final_confirmation_*"):
        path = run / "cat-gold-b_result.json"
        if path.exists():
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError("No saved CAT-GOLD-B result was found.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def main() -> None:
    result_path = _latest_gold_b_result()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    evaluation = evaluate_gold_result(result)

    print("\n=== GOLD B OFFLINE FINAL-SCORING INSPECTION ===")
    print("Result:", result_path)
    print("External calls: 0")
    print("Extraction status:", result.get("extraction_status"))
    if evaluation is None:
        print("Final evaluation: unavailable")
        return

    metric = evaluation["metric_association_v2"]
    normalization = evaluation.get("normalization_source_review") or {}
    print("Metric association:", f"{metric.get('matched_count')}/{metric.get('expected_count')}")
    for item in metric.get("results", []):
        if not item.get("matched"):
            print("MISSING |", json.dumps(item.get("expected"), ensure_ascii=False))
    print(
        "Normalization source review:",
        f"{normalization.get('matched_count')}/{normalization.get('expected_count')}",
    )
    for item in normalization.get("results", []):
        print(
            "PASS" if item.get("matched") else "FAIL",
            "|",
            json.dumps(item, ensure_ascii=False),
        )
    print("Overall Gold B:", "PASS" if evaluation_complete(evaluation) else "SCIENTIFIC_GAP")


if __name__ == "__main__":
    main()
