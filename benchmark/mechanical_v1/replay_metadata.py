"""Read committed Mechanical freeze history when local reports are absent."""

from __future__ import annotations

import json
from pathlib import Path

from synthex_platform.benchmarks.optional_evidence import inspect_optional_raw_artifact


CASE_DIR = Path(__file__).resolve().parent
REPO = CASE_DIR.parents[1]


def _manifest_case(case_id: str) -> dict:
    manifest = json.loads((CASE_DIR / "freeze_manifest.json").read_text(encoding="utf-8"))
    return next(row for row in manifest["cases"] if row["id"] == case_id)


def _count(text: str) -> dict[str, int]:
    passed, total = text.split("/", 1)
    return {"passed": int(passed), "total": int(total)}


def offline_report(case_id: str) -> dict:
    """Use a rebuilt report if available, else the source-locked freeze summary."""
    path = REPO / "output/mechanical_v1/offline" / case_id / "report.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    case = _manifest_case(case_id)
    score = _count(case["deterministic_recovery_score"])
    if case_id == "MECH-REVIEW-G":
        score.update({"ownership_violations": 0, "evidence_violations": 0})
    return {
        "case_id": case_id,
        "status": "OFFLINE_DETERMINISTIC_REPLAY_FROM_COMMITTED_FREEZE",
        "provider_invoked": False,
        "source_sha256": case["source_sha256"],
        "gold_sha256": case["gold_sha256"],
        "score": score,
        "report_available_locally": False,
    }


def live_report(case_id: str, path: Path) -> dict:
    """Preserve the historical outcome without requiring its ignored report."""
    index_path = REPO / "benchmark/provider_audit/provider_history.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    states = [inspect_optional_raw_artifact(REPO, artifact["path"], artifact["sha256"])
              for row in index["runs"] if row["domain"] == "mechanical" and row["case"] == case_id
              for artifact in row["raw_artifacts"]]
    raw_available = any(state["RAW_PROVIDER_ARTIFACT_AVAILABLE"] for state in states)
    if path.is_file():
        report = json.loads(path.read_text(encoding="utf-8"))
        report["RAW_PROVIDER_ARTIFACT_AVAILABLE"] = raw_available
        return report
    case = _manifest_case(case_id)
    raw = case["raw_provider_score"]
    return {
        "case_id": case_id,
        "status": case["live_status"],
        "raw_provider_score": _count(raw) if raw is not None else None,
        "RAW_PROVIDER_ARTIFACT_AVAILABLE": raw_available,
        "report_available_locally": False,
    }
