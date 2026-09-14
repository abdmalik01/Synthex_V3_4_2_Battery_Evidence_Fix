"""Run one Gold A follow-up checkpoint without overwriting Stage 3 artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from benchmark_catalysis_stage3 import BENCHMARK_ROOT, run


OUTPUTS = BENCHMARK_ROOT / "outputs"
FOLLOWUP_OUTPUTS = OUTPUTS / "gold_a_followup"
SUMMARY_PATH = OUTPUTS / "stage3_gold_a_followup_run_summary.json"
LEDGER_PATH = OUTPUTS / "stage3_gold_a_followup_execution_ledger.json"


def run_followup() -> dict:
    summary = run(
        {"CAT-GOLD-A"},
        output_dir=FOLLOWUP_OUTPUTS,
        summary_filename="run_summary.json",
        capture_model_outputs=True,
    )
    result = summary["results"][0]
    summary["followup"] = {
        "scope": "Gold A checkpoint only",
        "seven_paper_corpus_rerun": False,
        "historical_artifacts_modified": False,
        "target_conversions_passed": (
            result.get("extraction_status") == "schema_valid"
            and all(
                item.get("matched") is True
                for item in (result.get("gold_score") or {}).get("metric_association", {}).get("results", [])[:2]
            )
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = {"runs": []}
    if LEDGER_PATH.exists():
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    ledger["runs"].append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": "CAT-GOLD-A",
        "extraction_status": result.get("extraction_status"),
        "error_type": result.get("error_type"),
        "gemini_calls": result.get("gemini_calls", 0),
        "repair_calls": result.get("repair_calls", 0),
        "serper_enabled": False,
        "target_conversions_passed": summary["followup"]["target_conversions_passed"],
        "captured_model_outputs": result.get("captured_model_outputs", {}),
    })
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    summary = run_followup()
    result = summary["results"][0]
    print(json.dumps({
        "benchmark_id": result["benchmark_id"],
        "extraction_status": result["extraction_status"],
        "gemini_calls": result.get("gemini_calls", 0),
        "repair_calls": result.get("repair_calls", 0),
        "metric_association": (result.get("gold_score") or {}).get("metric_association"),
        "target_conversions_passed": summary["followup"]["target_conversions_passed"],
        "captured_model_outputs": result.get("captured_model_outputs", {}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
