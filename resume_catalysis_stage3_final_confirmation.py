"""Resume only unresolved Catalysis Stage 3 final-confirmation papers.

This script reuses the latest saved final-confirmation report, skips papers that
already passed, reruns only unresolved benchmark IDs in fresh per-paper output
folders, and stops immediately when a hard quota-exhaustion (HTTP 429 /
RESOURCE_EXHAUSTED) response is encountered. It remains pinned to the existing
Stage 3 benchmark runner (gemini-3.5-flash, benchmark mode, no Serper).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from benchmark_catalysis_scoring_v2 import score_metric_association
from benchmark_catalysis_stage3 import BENCHMARK_ROOT, run


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"
GOLD_PATHS = {
    "CAT-GOLD-A": BENCHMARK_ROOT / "gold" / "gold_a_heterogeneous_experimental.json",
    "CAT-GOLD-B": BENCHMARK_ROOT / "gold" / "gold_b_electrocatalysis.json",
}


def _latest_final_confirmation() -> Path:
    candidates = sorted(
        [path for path in OUTPUT_ROOT.glob("stage3_final_confirmation_*") if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        if (path / "final_confirmation_report.json").exists():
            return path
    raise FileNotFoundError("No prior Stage 3 final-confirmation report was found.")


def _gold_document(result: dict[str, Any]) -> dict[str, Any] | None:
    archive = result.get("archive") or {}
    for payload in archive.get("domain_payloads", []):
        if payload.get("domain") == "catalysis":
            values = payload.get("values") or {}
            document = values.get("validated_document")
            if isinstance(document, dict):
                return document
    return None


def _metric_v2(result: dict[str, Any]) -> dict[str, Any] | None:
    path = GOLD_PATHS.get(result.get("benchmark_id"))
    document = _gold_document(result)
    if path is None or document is None:
        return None
    gold = json.loads(path.read_text(encoding="utf-8"))
    return score_metric_association(gold, document)


def _provider_blocked(result: dict[str, Any]) -> bool:
    if result.get("extraction_status") != "pipeline_error":
        return False
    text = f"{result.get('error_type') or ''} {result.get('error_message') or ''}".casefold()
    return any(token in text for token in (
        "503", "unavailable", "high demand",
        "429", "resource_exhausted", "quota exceeded",
    ))


def _quota_exhausted(result: dict[str, Any]) -> bool:
    text = f"{result.get('error_type') or ''} {result.get('error_message') or ''}".casefold()
    return any(token in text for token in ("429", "resource_exhausted", "quota exceeded"))


def _status(result: dict[str, Any]) -> str:
    extraction = result.get("extraction_status")
    if extraction == "routing_only_negative_control":
        return "PASS"
    if _provider_blocked(result):
        return "PROVIDER_BLOCKED"
    if extraction != "schema_valid":
        return "FAIL"
    metric = _metric_v2(result)
    if metric is not None and metric.get("matched_count") != metric.get("expected_count"):
        return "SCIENTIFIC_GAP"
    return "PASS"


def main() -> None:
    prior_dir = _latest_final_confirmation()
    prior_report = json.loads((prior_dir / "final_confirmation_report.json").read_text(encoding="utf-8"))
    unresolved = [
        item["benchmark_id"]
        for item in prior_report.get("papers", [])
        if item.get("status") != "PASS"
    ]
    if not unresolved:
        print("All papers in the latest final confirmation already passed. Nothing to resume.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    resume_dir = OUTPUT_ROOT / f"stage3_final_resume_{stamp}"
    resume_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== CATALYSIS STAGE 3 RESUME ===")
    print("Base run:", prior_dir)
    print("Unresolved IDs:", ", ".join(unresolved))
    print("Model: gemini-3.5-flash")
    print("Provider mode: benchmark (pinned; no failover)")
    print("Serper enabled: False")

    results: list[dict[str, Any]] = []
    stopped_for_quota = False

    for benchmark_id in unresolved:
        paper_dir = resume_dir / benchmark_id.lower()
        summary = run(
            {benchmark_id},
            output_dir=paper_dir,
            summary_filename="resume_summary.json",
            capture_model_outputs=True,
            capture_candidate_inventory=True,
        )
        result = summary["results"][0]
        metric = _metric_v2(result)
        if metric is not None:
            result["gold_metric_association_v2"] = metric
        paper_status = _status(result)
        record = {
            "benchmark_id": benchmark_id,
            "status": paper_status,
            "extraction_status": result.get("extraction_status"),
            "gemini_calls": result.get("gemini_calls", 0),
            "repair_calls": result.get("repair_calls", 0),
            "coverage_calls": result.get("coverage_calls", 0),
            "gold_metric_association_v2": metric,
            "error_type": result.get("error_type"),
            "error_message": result.get("error_message"),
            "output_dir": str(paper_dir),
        }
        results.append(record)

        line = (
            f"{benchmark_id}: {paper_status} | extraction={record['extraction_status']} | "
            f"calls={record['gemini_calls']} | repair={record['repair_calls']} | "
            f"coverage={record['coverage_calls']}"
        )
        if metric is not None:
            line += f" | metric_v2={metric.get('matched_count')}/{metric.get('expected_count')}"
        print(line)
        if record["error_type"]:
            print("  Error:", record["error_type"], "|", str(record["error_message"])[:700])

        if _quota_exhausted(result):
            stopped_for_quota = True
            print("Stopping remaining retries because provider quota is exhausted.")
            break

    attempted = {item["benchmark_id"] for item in results}
    skipped_due_quota = [item for item in unresolved if item not in attempted]
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_final_confirmation": str(prior_dir),
        "model": "gemini-3.5-flash",
        "provider_mode": "benchmark",
        "serper_enabled": False,
        "requested_unresolved_ids": unresolved,
        "results": results,
        "stopped_for_quota": stopped_for_quota,
        "skipped_due_quota": skipped_due_quota,
        "output_dir": str(resume_dir),
    }
    report_path = resume_dir / "resume_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Resume outputs:", resume_dir)
    print("Report:", report_path)
    if skipped_due_quota:
        print("Not attempted after quota stop:", ", ".join(skipped_due_quota))


if __name__ == "__main__":
    main()
