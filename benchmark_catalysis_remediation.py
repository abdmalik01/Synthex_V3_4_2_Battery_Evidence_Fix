"""Run the bounded post-Stage-3 Catalysis remediation without touching Stage 3 artifacts."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_gold import contextual_value_match
from benchmark_catalysis_stage3 import BENCHMARK_ROOT, GOLD, _observed_metrics, run


OUTPUTS = BENCHMARK_ROOT / "outputs"
REMEDIATION_ROOT = BENCHMARK_ROOT / "remediation"
ADJUSTMENTS_PATH = REMEDIATION_ROOT / "gold_adjustments.json"
SUMMARY_PATH = OUTPUTS / "stage3_remediation_run_summary.json"
LEDGER_PATH = OUTPUTS / "stage3_remediation_execution_ledger.json"


def load_remediation_gold() -> dict[str, dict[str, Any]]:
    records = {
        benchmark_id: json.loads(path.read_text(encoding="utf-8"))
        for benchmark_id, path in GOLD.items()
    }
    adjustments = json.loads(ADJUSTMENTS_PATH.read_text(encoding="utf-8"))
    record = deepcopy(records[adjustments["benchmark_id"]])
    for adjustment in adjustments["adjustments"]:
        selector = adjustment["selector"]
        matches = [
            metric for metric in record["metrics"]
            if all(metric.get(key) == value for key, value in selector.items())
        ]
        if len(matches) != 1:
            raise ValueError(f"Remediation gold selector matched {len(matches)} metrics: {selector}")
        matches[0].pop(adjustment["remove_expected_field"], None)
    record["remediation_review"] = adjustments
    records[adjustments["benchmark_id"]] = record
    return records


def normalization_source_review(document: dict[str, Any]) -> dict[str, Any]:
    adjustments = json.loads(ADJUSTMENTS_PATH.read_text(encoding="utf-8"))["adjustments"]
    observed = _observed_metrics(document)
    results = []
    for adjustment in adjustments:
        selector = adjustment["selector"]
        candidates = [item for item in observed if contextual_value_match(selector, item)]
        correct = bool(candidates) and all(
            item.get("normalization_basis") in (None, "unknown") for item in candidates
        )
        results.append({
            "selector": selector,
            "expected": "unknown_or_absent",
            "observed": [item.get("normalization_basis") for item in candidates],
            "matched": correct,
        })
    return {
        "expected_count": len(results),
        "matched_count": sum(item["matched"] for item in results),
        "results": results,
        "gold_adjustment": str(ADJUSTMENTS_PATH.relative_to(BENCHMARK_ROOT)),
    }


def _document(result: dict[str, Any]) -> dict[str, Any] | None:
    payloads = [
        item for item in (result.get("archive") or {}).get("domain_payloads", [])
        if item.get("domain") == "catalysis"
    ]
    return payloads[0]["values"]["validated_document"] if payloads else None


def _totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    catalysis = [item for item in results if item.get("route", {}).get("domain") == "catalysis"]
    valid = [item for item in catalysis if item.get("extraction_status") == "schema_valid"]
    safety_keys = ("dft_experimental_leakage", "review_contamination", "digitized_canonical_leakage")
    return {
        "papers": len(results),
        "routing_correct": sum(item.get("route_correct") is True for item in results),
        "subtypes_correct": sum(item.get("subtypes_correct") is True for item in results),
        "scope_correct": sum(item.get("scope_correct") is True for item in results),
        "catalysis_extractions_attempted": len(catalysis),
        "schema_valid_final": len(valid),
        "persistent_failures": len(catalysis) - len(valid),
        "gemini_calls": sum(int(item.get("gemini_calls", 0)) for item in results),
        "repair_calls": sum(int(item.get("repair_calls", 0)) for item in results),
        "safety": {
            **{
                key: sum(int((item.get("safety") or {}).get(key, 0)) for item in results)
                for key in safety_keys
            },
            "referential_integrity_failures": sum(
                len((item.get("safety") or {}).get("referential_integrity_violations", []))
                for item in results
            ),
        },
    }


def run_remediation(phase: str) -> dict[str, Any]:
    selected = {"CAT-GOLD-A", "CAT-GOLD-B"} if phase == "gold-only" else None
    phase_dir = OUTPUTS / "remediation" / phase
    summary = run(
        selected,
        output_dir=phase_dir,
        summary_filename="run_summary.json",
        gold_records=load_remediation_gold(),
    )
    for result in summary["results"]:
        if result["benchmark_id"] != "CAT-GOLD-B":
            continue
        document = _document(result)
        if document is not None:
            result.setdefault("gold_score", {})["normalization_source_review"] = normalization_source_review(document)
            (phase_dir / "cat-gold-b_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    summary.update({
        "remediation_phase": phase,
        "historical_stage3_artifacts_modified": False,
        "final_outcome_totals": _totals(summary["results"]),
    })
    (phase_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    ledger = {"runs": []}
    if LEDGER_PATH.exists():
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    ledger["runs"].append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "paper_ids": [item["benchmark_id"] for item in summary["results"]],
        "gemini_calls": summary["final_outcome_totals"]["gemini_calls"],
        "repair_calls": summary["final_outcome_totals"]["repair_calls"],
        "serper_enabled": False,
        "output_directory": str(phase_dir.relative_to(BENCHMARK_ROOT)),
    })
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("gold-only", "full"), required=True)
    args = parser.parse_args()
    summary = run_remediation(args.phase)
    print(json.dumps({
        "phase": args.phase,
        "results": [
            {
                "benchmark_id": item["benchmark_id"],
                "extraction_status": item["extraction_status"],
                "metric_association": (item.get("gold_score") or {}).get("metric_association"),
                "normalization_source_review": (item.get("gold_score") or {}).get("normalization_source_review"),
            }
            for item in summary["results"]
        ],
        "totals": summary["final_outcome_totals"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
