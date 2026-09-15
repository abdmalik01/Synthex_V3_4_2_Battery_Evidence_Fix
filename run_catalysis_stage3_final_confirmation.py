"""Run one isolated final Catalysis Stage 3 seven-paper confirmation.

The underlying Stage 3 runner remains pinned to gemini-3.5-flash in benchmark mode,
uses no Serper calls, and writes into a fresh timestamped directory so historical
benchmark artifacts are not overwritten. Final Gold scoring is remediation-aware:
historical Gold files remain untouched, while Gold B uses the reviewed overlay
that removes the unsupported geometric-area normalization expectation and checks
unknown/absent normalization explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_final_scoring import evaluate_gold_result, evaluation_complete
from benchmark_catalysis_stage3 import run


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"
_PROVIDER_BLOCK_TOKENS = (
    "503", "unavailable", "high demand",
    "429", "resource_exhausted", "quota exceeded", "rate limit",
)


def _provider_blocked(result: dict[str, Any]) -> bool:
    if result.get("extraction_status") != "pipeline_error":
        return False
    message = str(result.get("error_message") or "").casefold()
    return any(token in message for token in _PROVIDER_BLOCK_TOKENS)


def _paper_status(result: dict[str, Any], gold_evaluation: dict[str, Any] | None = None) -> str:
    status = result.get("extraction_status")
    if status == "routing_only_negative_control":
        return "PASS"
    if status == "schema_valid":
        return "PASS" if evaluation_complete(gold_evaluation) else "SCIENTIFIC_GAP"
    if _provider_blocked(result):
        return "PROVIDER_BLOCKED"
    return "FAIL"


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = OUTPUT_ROOT / f"stage3_final_confirmation_{stamp}"
    summary = run(
        None,
        output_dir=output_dir,
        summary_filename="stage3_final_confirmation_summary.json",
        capture_model_outputs=True,
        capture_candidate_inventory=True,
    )

    paper_reports = []
    provider_blocked = False
    scientific_failures = False
    safety_totals = {
        "dft_experimental_leakage": 0,
        "review_contamination": 0,
        "digitized_canonical_leakage": 0,
        "unsupported_potential_conversions": 0,
        "referential_integrity_violations": 0,
    }

    for result in summary.get("results", []):
        gold_evaluation = evaluate_gold_result(result)
        metric_v2 = (gold_evaluation or {}).get("metric_association_v2")
        normalization_review = (gold_evaluation or {}).get("normalization_source_review")
        if gold_evaluation is not None:
            result["gold_final_evaluation"] = gold_evaluation
            result["gold_metric_association_v2"] = metric_v2
            if normalization_review is not None:
                result["gold_normalization_source_review"] = normalization_review
            result_path = output_dir / f"{result['benchmark_id'].lower()}_result.json"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        status = _paper_status(result, gold_evaluation)
        provider_blocked = provider_blocked or status == "PROVIDER_BLOCKED"
        scientific_failures = scientific_failures or status in {"FAIL", "SCIENTIFIC_GAP"}
        safety = result.get("safety") or {}
        for key in ("dft_experimental_leakage", "review_contamination", "digitized_canonical_leakage"):
            safety_totals[key] += int(safety.get(key, 0) or 0)
        gold_score = result.get("gold_score") or {}
        safety_totals["unsupported_potential_conversions"] += int(gold_score.get("unsupported_potential_conversions", 0) or 0)
        safety_totals["referential_integrity_violations"] += len(gold_score.get("referential_integrity_violations", []) or [])

        paper_reports.append({
            "benchmark_id": result.get("benchmark_id"),
            "status": status,
            "route_correct": result.get("route_correct"),
            "scope_correct": result.get("scope_correct"),
            "subtypes_correct": result.get("subtypes_correct"),
            "extraction_status": result.get("extraction_status"),
            "gemini_calls": result.get("gemini_calls", 0),
            "repair_calls": result.get("repair_calls", 0),
            "coverage_calls": result.get("coverage_calls", 0),
            "gold_final_evaluation": gold_evaluation,
            "gold_metric_association_v2": metric_v2,
            "gold_normalization_source_review": normalization_review,
            "gold_score": gold_score or None,
            "error_type": result.get("error_type"),
            "error_message": result.get("error_message"),
        })

    routing_ok = all(
        item.get("route_correct") is True
        and item.get("scope_correct") is True
        and item.get("subtypes_correct") is True
        for item in summary.get("results", [])
    )
    safety_ok = all(value == 0 for value in safety_totals.values())

    if provider_blocked and scientific_failures:
        overall_status = "PROVIDER_BLOCKED_WITH_SCIENTIFIC_GAPS"
    elif provider_blocked:
        overall_status = "PROVIDER_BLOCKED"
    elif scientific_failures or not routing_ok or not safety_ok:
        overall_status = "FAILED"
    else:
        overall_status = "COMPLETE"

    report = {
        "run_at": summary.get("run_at"),
        "model": summary.get("model"),
        "provider_mode": "benchmark",
        "serper_enabled": summary.get("serper_enabled"),
        "overall_status": overall_status,
        "routing_ok": routing_ok,
        "safety_ok": safety_ok,
        "safety_totals": safety_totals,
        "totals": summary.get("totals", {}),
        "papers": paper_reports,
        "output_dir": str(output_dir),
    }
    (output_dir / "final_confirmation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== CATALYSIS STAGE 3 FINAL CONFIRMATION ===")
    print("Overall status:", overall_status)
    print("Model:", summary.get("model"))
    print("Provider mode: benchmark (pinned; no failover)")
    print("Serper enabled:", summary.get("serper_enabled"))
    print("Routing/scope/subtypes:", "PASS" if routing_ok else "FAIL")
    print("Safety gates:", "PASS" if safety_ok else "FAIL", safety_totals)
    print("Total Gemini calls:", (summary.get("totals") or {}).get("gemini_calls", 0))
    print("Total repair calls:", (summary.get("totals") or {}).get("repair_calls", 0))

    for paper in paper_reports:
        line = (
            f"{paper['benchmark_id']}: {paper['status']} | "
            f"extraction={paper['extraction_status']} | "
            f"calls={paper['gemini_calls']} | repair={paper['repair_calls']} | "
            f"coverage={paper['coverage_calls']}"
        )
        metric = paper.get("gold_metric_association_v2")
        if metric:
            line += f" | metric_v2={metric.get('matched_count')}/{metric.get('expected_count')}"
        normalization = paper.get("gold_normalization_source_review")
        if normalization:
            line += f" | normalization={normalization.get('matched_count')}/{normalization.get('expected_count')}"
        print(line)
        if paper.get("error_type"):
            print("  Error:", paper.get("error_type"), "|", paper.get("error_message"))

    print("Outputs:", output_dir)
    print("Report:", output_dir / "final_confirmation_report.json")


if __name__ == "__main__":
    main()
