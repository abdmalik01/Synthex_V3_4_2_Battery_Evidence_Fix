"""Run the pinned Catalysis Gold A checkpoint without overwriting historical Stage 3 artifacts.

This wrapper does not change extraction science. It calls the existing Stage 3 runner for CAT-GOLD-A,
uses the historically pinned benchmark model configured there, writes to a fresh output directory,
and translates provider-capacity failures into an explicit checkpoint status.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_stage3 import run


ROOT = Path(__file__).resolve().parent
CHECKPOINT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"
_PROVIDER_BLOCKING_CLASSES = {
    "provider_unavailable",
    "model_unavailable",
    "timeout",
    "transport_failure",
    "quota",
}


def _provider_failure_classes(result: dict[str, Any]) -> list[str]:
    provider = result.get("provider") or {}
    failures = provider.get("provider_failures") or []
    classes = []
    for item in failures:
        value = item.get("failure_class") if isinstance(item, dict) else None
        if value and value not in classes:
            classes.append(value)
    return classes


def classify_checkpoint(result: dict[str, Any]) -> str:
    """Classify execution separately from scientific Gold A success/failure."""
    extraction_status = result.get("extraction_status")
    if extraction_status == "schema_valid":
        return "SCIENTIFIC_RESULT_AVAILABLE"
    failure_classes = set(_provider_failure_classes(result))
    if failure_classes & _PROVIDER_BLOCKING_CLASSES:
        return "PROVIDER_BLOCKED"
    if result.get("error_type") in {"ServerError", "ClientError"}:
        message = str(result.get("error_message") or "").casefold()
        if "503" in message or "unavailable" in message or "high demand" in message:
            return "PROVIDER_BLOCKED"
    return "PIPELINE_FAILED"


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = CHECKPOINT_ROOT / f"gold_a_checkpoint_{stamp}"
    summary = run(
        {"CAT-GOLD-A"},
        output_dir=output_dir,
        summary_filename="gold_a_checkpoint_summary.json",
        capture_model_outputs=True,
        capture_candidate_inventory=True,
    )
    result = summary["results"][0]
    checkpoint_status = classify_checkpoint(result)
    score = result.get("gold_score") or {}
    metric = score.get("metric_association") or {}
    report = {
        "checkpoint_status": checkpoint_status,
        "scientific_evaluation_performed": result.get("extraction_status") == "schema_valid",
        "model": summary.get("model"),
        "extraction_status": result.get("extraction_status"),
        "gemini_calls": result.get("gemini_calls", 0),
        "repair_calls": result.get("repair_calls", 0),
        "coverage_calls": result.get("coverage_calls", 0),
        "provider_failure_classes": _provider_failure_classes(result),
        "error_type": result.get("error_type"),
        "error_message": result.get("error_message"),
        "gold_metric_association": {
            "matched_count": metric.get("matched_count"),
            "expected_count": metric.get("expected_count"),
            "results": metric.get("results", []),
        },
        "output_dir": str(output_dir),
    }
    (output_dir / "checkpoint_status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== GOLD A CHECKPOINT ===")
    print("Checkpoint status:", checkpoint_status)
    print("Extraction status:", result.get("extraction_status"))
    print("Model:", summary.get("model"))
    print("Gemini calls:", result.get("gemini_calls", 0))
    print("Repair calls:", result.get("repair_calls", 0))
    print("Coverage calls:", result.get("coverage_calls", 0))
    if report["provider_failure_classes"]:
        print("Provider failure classes:", ", ".join(report["provider_failure_classes"]))
    if metric:
        print("Gold metric association:", f"{metric.get('matched_count')}/{metric.get('expected_count')}")
        for item in metric.get("results", []):
            print("PASS" if item.get("matched") else "FAIL", "|", json.dumps(item.get("expected"), ensure_ascii=False))
    if result.get("error_type"):
        print("Error type:", result.get("error_type"))
        print("Error:", result.get("error_message"))
    print("Outputs:", output_dir)


if __name__ == "__main__":
    main()
