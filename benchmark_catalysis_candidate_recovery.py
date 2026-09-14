"""Run isolated Stage 3 candidate-recovery checkpoints.

This runner never overwrites historical Stage 3 output, report, or ledger files.
It is intentionally opt-in and never starts the seven-paper corpus implicitly.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from benchmark_catalysis_stage3 import BENCHMARK_ROOT, run


OUTPUTS = BENCHMARK_ROOT / "outputs" / "candidate_recovery"
SUMMARY = BENCHMARK_ROOT / "outputs" / "stage3_candidate_recovery_run_summary.json"
LEDGER = BENCHMARK_ROOT / "outputs" / "stage3_candidate_recovery_execution_ledger.json"


def _target_conversions_pass(result: dict) -> bool:
    rows = ((result.get("gold_score") or {}).get("metric_association") or {}).get("results", [])
    return result.get("extraction_status") == "schema_valid" and len(rows) >= 2 and all(
        item.get("matched") is True for item in rows[:2]
    )


def run_checkpoint(ids: set[str]) -> dict:
    if not ids or not ids.issubset({"CAT-GOLD-A", "CAT-GOLD-B"}):
        raise ValueError("Candidate recovery checkpoint permits only CAT-GOLD-A and CAT-GOLD-B.")
    summary = run(
        ids,
        output_dir=OUTPUTS,
        summary_filename="checkpoint_run_summary.json",
        capture_model_outputs=True,
        capture_candidate_inventory=True,
    )
    results = {item["benchmark_id"]: item for item in summary["results"]}
    gate = _target_conversions_pass(results["CAT-GOLD-A"]) if "CAT-GOLD-A" in results else None
    summary["candidate_recovery_checkpoint"] = {
        "selected_ids": sorted(ids),
        "gold_a_gate_passed": gate,
        "seven_paper_corpus_rerun": False,
        "historical_artifacts_modified": False,
        "serper_enabled": False,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = {"runs": []}
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    ledger["runs"].append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "selected_ids": sorted(ids),
        "gold_a_gate_passed": gate,
        "serper_enabled": False,
        "results": [{
            "benchmark_id": item["benchmark_id"],
            "extraction_status": item.get("extraction_status"),
            "primary_calls": item.get("primary_calls", 0),
            "schema_repair_calls": item.get("schema_repair_calls", item.get("repair_calls", 0)),
            "coverage_calls": item.get("coverage_calls", 0),
            "gemini_calls": item.get("gemini_calls", 0),
            "candidates_detected": item.get("candidates_detected", 0),
            "high_priority_candidates": item.get("high_priority_candidates", 0),
            "candidates_covered": item.get("candidates_covered", 0),
            "candidates_sent": item.get("candidates_sent", 0),
            "coverage_candidates_accepted": item.get("coverage_candidates_accepted", 0),
            "coverage_candidates_rejected": item.get("coverage_candidates_rejected", 0),
            "captured_model_outputs": item.get("captured_model_outputs", {}),
            "candidate_artifacts": item.get("candidate_artifacts", {}),
        } for item in summary["results"]],
    })
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", required=True, choices=["CAT-GOLD-A", "CAT-GOLD-B"])
    args = parser.parse_args()
    summary = run_checkpoint(set(args.ids))
    print(json.dumps({
        "checkpoint": summary["candidate_recovery_checkpoint"],
        "results": [{
            key: item.get(key) for key in (
                "benchmark_id", "extraction_status", "gemini_calls", "primary_calls",
                "schema_repair_calls", "coverage_calls", "candidates_detected",
                "high_priority_candidates", "candidates_covered", "candidates_sent",
                "coverage_candidates_accepted", "coverage_candidates_rejected",
            )
        } for item in summary["results"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
