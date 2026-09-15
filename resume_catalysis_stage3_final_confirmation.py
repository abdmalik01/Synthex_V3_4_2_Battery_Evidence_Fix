"""Resume only unresolved Catalysis Stage 3 final-confirmation papers.

This script is cumulative. It starts from the latest saved final-confirmation run,
recomputes each paper status from the saved result, then folds in every later
resume report and keeps the latest successful resolution for each benchmark ID.
Only still-unresolved IDs are rerun in fresh per-paper output folders.

Final Gold scoring is remediation-aware. Historical Gold files remain untouched;
Gold B uses the reviewed remediation overlay and separately verifies that the two
partial-current-density normalization bases remain unknown/absent.

The underlying Stage 3 runner remains pinned to gemini-3.5-flash in benchmark
mode, with no Serper calls and no silent model failover. The script stops
immediately on hard quota exhaustion (HTTP 429 / RESOURCE_EXHAUSTED).
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


def _status(result: dict[str, Any], gold_evaluation: dict[str, Any] | None = None) -> str:
    extraction = result.get("extraction_status")
    if extraction == "routing_only_negative_control":
        return "PASS"
    if _provider_blocked(result):
        return "PROVIDER_BLOCKED"
    if extraction != "schema_valid":
        return "FAIL"
    if gold_evaluation is None:
        gold_evaluation = evaluate_gold_result(result)
    return "PASS" if evaluation_complete(gold_evaluation) else "SCIENTIFIC_GAP"


def _result_state(result: dict[str, Any], source: str) -> dict[str, Any]:
    evaluation = evaluate_gold_result(result)
    return {
        "benchmark_id": result.get("benchmark_id"),
        "status": _status(result, evaluation),
        "extraction_status": result.get("extraction_status"),
        "gold_final_evaluation": evaluation,
        "gold_metric_association_v2": (evaluation or {}).get("metric_association_v2"),
        "gold_normalization_source_review": (evaluation or {}).get("normalization_source_review"),
        "source": source,
    }


def _base_results(prior_dir: Path) -> dict[str, dict[str, Any]]:
    report = json.loads((prior_dir / "final_confirmation_report.json").read_text(encoding="utf-8"))
    resolved: dict[str, dict[str, Any]] = {}
    for paper in report.get("papers", []):
        benchmark_id = paper.get("benchmark_id")
        if not benchmark_id:
            continue
        result_path = prior_dir / f"{benchmark_id.lower()}_result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            resolved[benchmark_id] = _result_state(result, str(result_path))
        else:
            resolved[benchmark_id] = {
                "benchmark_id": benchmark_id,
                "status": paper.get("status") or "FAIL",
                "extraction_status": paper.get("extraction_status"),
                "gold_final_evaluation": paper.get("gold_final_evaluation"),
                "gold_metric_association_v2": paper.get("gold_metric_association_v2"),
                "gold_normalization_source_review": paper.get("gold_normalization_source_review"),
                "source": str(prior_dir / "final_confirmation_report.json"),
            }
    return resolved


def _resume_result_file(item: dict[str, Any]) -> Path | None:
    output_dir = item.get("output_dir")
    benchmark_id = item.get("benchmark_id")
    if not output_dir or not benchmark_id:
        return None
    candidate = Path(output_dir) / f"{benchmark_id.lower()}_result.json"
    return candidate if candidate.exists() else None


def _apply_resume_history(
    state: dict[str, dict[str, Any]], prior_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Fold in resume runs newer than the base final confirmation.

    Saved per-paper result JSON is preferred over the report label so updated
    remediation-aware scoring can re-evaluate old resume outputs offline. PASS
    replaces any earlier state. A later non-PASS result never erases an already
    established PASS, preventing transient provider errors from regressing a
    scientifically completed paper.
    """
    candidates = sorted(
        [path for path in OUTPUT_ROOT.glob("stage3_final_resume_*") if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
    )
    base_mtime = prior_dir.stat().st_mtime
    for path in candidates:
        if path.stat().st_mtime < base_mtime:
            continue
        report_path = path / "resume_report.json"
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for item in report.get("results", []):
            benchmark_id = item.get("benchmark_id")
            if not benchmark_id:
                continue
            result_path = _resume_result_file(item)
            if result_path is not None:
                incoming = _result_state(
                    json.loads(result_path.read_text(encoding="utf-8")), str(result_path)
                )
            else:
                incoming = {
                    "benchmark_id": benchmark_id,
                    "status": item.get("status") or "FAIL",
                    "extraction_status": item.get("extraction_status"),
                    "gold_final_evaluation": item.get("gold_final_evaluation"),
                    "gold_metric_association_v2": item.get("gold_metric_association_v2"),
                    "gold_normalization_source_review": item.get("gold_normalization_source_review"),
                    "source": str(report_path),
                }
            current = state.get(benchmark_id)
            if current and current.get("status") == "PASS" and incoming.get("status") != "PASS":
                continue
            state[benchmark_id] = incoming
    return state


def main() -> None:
    prior_dir = _latest_final_confirmation()
    state = _apply_resume_history(_base_results(prior_dir), prior_dir)
    unresolved = [
        benchmark_id
        for benchmark_id, item in state.items()
        if item.get("status") != "PASS"
    ]
    if not unresolved:
        print("All papers in the latest final confirmation are resolved. Nothing to resume.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    resume_dir = OUTPUT_ROOT / f"stage3_final_resume_{stamp}"
    resume_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== CATALYSIS STAGE 3 RESUME ===")
    print("Base run:", prior_dir)
    print("Unresolved IDs:", ", ".join(unresolved))
    for benchmark_id in unresolved:
        item = state[benchmark_id]
        metric = item.get("gold_metric_association_v2") or {}
        normalization = item.get("gold_normalization_source_review") or {}
        details = ""
        if metric:
            details += f" | metric_v2={metric.get('matched_count')}/{metric.get('expected_count')}"
        if normalization:
            details += f" | normalization={normalization.get('matched_count')}/{normalization.get('expected_count')}"
        print(f"  {benchmark_id}: prior_status={item.get('status')}{details}")
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
        evaluation = evaluate_gold_result(result)
        metric = (evaluation or {}).get("metric_association_v2")
        normalization = (evaluation or {}).get("normalization_source_review")
        if evaluation is not None:
            result["gold_final_evaluation"] = evaluation
            result["gold_metric_association_v2"] = metric
            if normalization is not None:
                result["gold_normalization_source_review"] = normalization
            result_path = paper_dir / f"{benchmark_id.lower()}_result.json"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        paper_status = _status(result, evaluation)
        record = {
            "benchmark_id": benchmark_id,
            "status": paper_status,
            "extraction_status": result.get("extraction_status"),
            "gemini_calls": result.get("gemini_calls", 0),
            "repair_calls": result.get("repair_calls", 0),
            "coverage_calls": result.get("coverage_calls", 0),
            "gold_final_evaluation": evaluation,
            "gold_metric_association_v2": metric,
            "gold_normalization_source_review": normalization,
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
        if normalization is not None:
            line += f" | normalization={normalization.get('matched_count')}/{normalization.get('expected_count')}"
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
        "prior_state": state,
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
