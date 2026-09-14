"""Inspect the latest saved Catalysis Stage 3 final confirmation without external calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_scoring_v2 import score_metric_association
from benchmark_catalysis_stage3 import BENCHMARK_ROOT


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"
GOLD_PATHS = {
    "CAT-GOLD-A": BENCHMARK_ROOT / "gold" / "gold_a_heterogeneous_experimental.json",
    "CAT-GOLD-B": BENCHMARK_ROOT / "gold" / "gold_b_electrocatalysis.json",
}
_PROVIDER_BLOCK_TOKENS = (
    "503", "unavailable", "high demand",
    "429", "resource_exhausted", "quota exceeded", "rate limit",
)


def latest_run() -> Path:
    runs = sorted(
        OUTPUT_ROOT.glob("stage3_final_confirmation_*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        raise SystemExit("No Stage 3 final confirmation directory found.")
    return runs[0]


def catalysis_document(result: dict[str, Any]) -> dict[str, Any] | None:
    archive = result.get("archive") or {}
    for payload in archive.get("domain_payloads", []):
        if payload.get("domain") == "catalysis":
            values = payload.get("values") or {}
            document = values.get("validated_document")
            if isinstance(document, dict):
                return document
    return None


def paper_status(result: dict[str, Any], metric: dict[str, Any] | None) -> str:
    extraction = result.get("extraction_status")
    if extraction == "routing_only_negative_control":
        return "PASS"
    if extraction == "schema_valid":
        if metric and metric.get("matched_count") != metric.get("expected_count"):
            return "SCIENTIFIC_GAP"
        return "PASS"
    message = str(result.get("error_message") or "").casefold()
    if extraction == "pipeline_error" and any(token in message for token in _PROVIDER_BLOCK_TOKENS):
        return "PROVIDER_BLOCKED"
    return "FAIL"


def main() -> None:
    run_dir = latest_run()
    print("\n=== CATALYSIS FINAL CONFIRMATION OFFLINE INSPECTION ===")
    print("Run:", run_dir)
    print("External calls: 0")

    result_files = sorted(run_dir.glob("cat-*_result.json"))
    if not result_files:
        raise SystemExit("No paper result JSON files found in latest final confirmation directory.")

    scientific_gaps = 0
    provider_blocks = 0
    hard_failures = 0

    for path in result_files:
        result = json.loads(path.read_text(encoding="utf-8"))
        benchmark_id = result.get("benchmark_id") or path.stem.replace("_result", "").upper()
        metric = None
        gold_path = GOLD_PATHS.get(benchmark_id)
        document = catalysis_document(result)
        if gold_path is not None and document is not None:
            gold = json.loads(gold_path.read_text(encoding="utf-8"))
            metric = score_metric_association(gold, document)

        status = paper_status(result, metric)
        scientific_gaps += status == "SCIENTIFIC_GAP"
        provider_blocks += status == "PROVIDER_BLOCKED"
        hard_failures += status == "FAIL"

        line = f"{benchmark_id}: {status} | extraction={result.get('extraction_status')}"
        if metric:
            line += f" | metric_v2={metric.get('matched_count')}/{metric.get('expected_count')}"
        print(line)

        if metric and metric.get("matched_count") != metric.get("expected_count"):
            for item in metric.get("results", []):
                if not item.get("matched"):
                    print("  MISSING |", json.dumps(item.get("expected"), ensure_ascii=False))

        if status == "PROVIDER_BLOCKED":
            print("  PROVIDER |", result.get("error_type"), "|", str(result.get("error_message") or "")[:300])
        elif status == "FAIL":
            print("  ERROR |", result.get("error_type"), "|", str(result.get("error_message") or "")[:300])

    print("\nSummary:")
    print("Scientific gaps:", scientific_gaps)
    print("Provider-blocked papers:", provider_blocks)
    print("Hard failures:", hard_failures)


if __name__ == "__main__":
    main()
