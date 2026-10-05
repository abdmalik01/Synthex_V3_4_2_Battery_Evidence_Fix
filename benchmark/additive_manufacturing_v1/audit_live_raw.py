"""Score persisted raw AM provider bodies without requiring canonical admission."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.score_mech_d_raw import score_mech_d_raw
from benchmark.additive_manufacturing_v1.score_micro_c_raw import score_micro_c_raw
from benchmark.additive_manufacturing_v1.score_post_e_raw import score_post_e_raw


CASES = {
    "AM-MICRO-C": ("micro_c_source_lock.json", score_micro_c_raw),
    "AM-MECH-D": ("mech_d_source_lock.json", score_mech_d_raw),
    "AM-POST-E": ("post_e_source_lock.json", score_post_e_raw),
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_case(case_id: str) -> dict:
    lock_name, scorer = CASES[case_id]
    _, gold, _ = load_locked(lock_name)
    case_root = ROOT / "output/additive_manufacturing_v1/live" / case_id
    latest = _json(case_root / "latest_run.json")
    run_root = Path(latest["path"])
    attempts = sorted(
        (path for path in run_root.glob("attempt-*") if (path / "raw_response.txt").exists()),
        key=lambda path: int(path.name.split("-")[-1]),
    )
    if not attempts:
        raise ValueError(f"{case_id} has no persisted raw provider body")
    attempt_root = attempts[-1]
    payload = _json(attempt_root / "raw_response.txt")
    score = scorer(payload, gold)
    (attempt_root / "raw_scientific_audit.json").write_text(
        json.dumps(score, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    report = _json(run_root / "report.json")
    provider_status = _json(attempt_root / "provider_status.json")
    repair_unavailable = (
        (attempt_root / "repair_request.txt").exists()
        and not (attempt_root / "repair_response.txt").exists()
        and any(
            item.get("phase") == "schema_repair" and item.get("status") == "failed"
            for item in provider_status.get("attempts", [])
        )
    )
    attempt_number = int(attempt_root.name.split("-")[-1])
    for item in report.get("provider_attempts", []):
        if item.get("attempt") == attempt_number:
            item["payload_returned"] = True
            item["schema_repair_count"] = int((attempt_root / "repair_request.txt").exists())
    report["actual_model"] = provider_status.get("actual_model")
    report["attempt_artifact_root"] = str(attempt_root)
    report["raw_provider_score"] = score
    report["canonical_admission_result"] = (
        "NOT_ADMITTED_RAW_SCHEMA_INVALID_REPAIR_UNAVAILABLE"
        if repair_unavailable else "NOT_ADMITTED_SCHEMA_INVALID"
    )
    if repair_unavailable:
        report["status"] = "LIVE_PAYLOAD_REPAIR_UNAVAILABLE"
        validation = _json(attempt_root / "raw_validation_report.json")
        report["raw_validation_errors"] = validation.get("errors", [])
        ledger_path = run_root / "provider_retry_ledger.json"
        ledger = _json(ledger_path)
        ledger["status"] = "LIVE_PAYLOAD_REPAIR_UNAVAILABLE"
        for item in ledger.get("attempts", []):
            if item.get("attempt") == attempt_number:
                item["payload_returned"] = True
                item["schema_repair_count"] = 1
        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    for path in (run_root / "report.json", case_root / "report.json"):
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    summaries = {}
    for case_id in CASES:
        report = audit_case(case_id)
        summaries[case_id] = {
            "status": report["status"],
            "actual_model": report["actual_model"],
            "canonical_admission_result": report["canonical_admission_result"],
        }
    print(json.dumps(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
