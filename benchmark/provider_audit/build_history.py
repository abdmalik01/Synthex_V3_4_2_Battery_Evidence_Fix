"""Regenerate a metadata-only audit of existing real Gemini benchmark reports.

No provider call is made. Raw bodies and provider error messages are never copied.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "output"
HERE = Path(__file__).resolve().parent
DOMAINS = {
    "mechanical_v1": "mechanical", "additive_manufacturing_v1": "additive_manufacturing",
    "photovoltaics_v1": "photovoltaics", "thermoelectrics_v1": "thermoelectrics",
    "membranes_v1": "membranes", "semiconductors_v1": "semiconductors",
    "biomaterials_v1": "biomaterials",
    "corrosion_v1": "corrosion", "battery_v1": "batteries", "catalysis_v1": "catalysis",
}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _score(score):
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return score
    if not isinstance(score, dict):
        return None
    accuracy = score.get("property_accuracy") or {}
    keep = ("passed", "total", "raw_output_count", "raw_record_count", "outputs", "expected_points", "exact_value_and_unit_points", "exact_property_key_points", "exact_sample_count", "table_locator_points", "page_locator_points", "verbatim_snippet_points", "exact_point_recall", "value_accuracy", "coordinate_accuracy")
    result = {key: score[key] for key in keep if key in score and isinstance(score[key], (int, float, bool))}
    if "exact_point_recall" in accuracy:
        result["exact_point_recall"] = accuracy["exact_point_recall"]
    return result or None


def _report_paths():
    for path in sorted(OUTPUT.glob("**/report.json")):
        rel = path.relative_to(OUTPUT).parts
        if len(rel) < 3 or rel[0] not in DOMAINS or "offline" in rel or "pytest" in str(path).casefold():
            continue
        if not ("provider_runs" in rel or "live" in rel):
            continue
        # A flat case report is an index when immutable child runs exist.
        if len(rel) == 4 and rel[1] == "live" and (path.parent / "runs").is_dir():
            continue
        yield path


def _entry(path: Path) -> dict:
    report = _load(path)
    if not isinstance(report, dict):
        raise ValueError(f"Invalid report: {path}")
    rel = path.relative_to(OUTPUT)
    domain = DOMAINS[rel.parts[0]]
    audit = report.get("provider_audit") or {}
    attempts = report.get("attempts") or report.get("provider_attempts") or audit.get("attempts") or []
    if isinstance(attempts, int):
        attempt_count = attempts
        attempts = []
    else:
        attempt_count = len(attempts)
    model = report.get("model_id") or report.get("actual_model") or report.get("model") or report.get("requested_model") or audit.get("actual_model") or audit.get("requested_model")
    payload = report.get("payload_returned")
    if payload is None and attempts:
        payload = any(a.get("payload_returned") is True or a.get("status") in {"payload_returned", "succeeded"} for a in attempts)
    raw_files = sorted([*path.parent.glob("attempt-*/raw_response.txt"), *path.parent.glob("provider_raw_response.json")])
    raw_artifacts = [{"path": f.relative_to(REPO).as_posix(), "sha256": _sha(f)} for f in raw_files]
    if payload is None and raw_artifacts:
        payload = True
    errors = sorted({str(a.get("provider_error_class") or a.get("failure_class") or a.get("status")) for a in attempts
                     if a.get("provider_error_class") or a.get("failure_class") or a.get("status") in {"provider_unavailable", "rate_limited", "failed"}})
    score = report.get("raw_scientific_score") or report.get("raw_provider_scientific_score") or report.get("raw_provider_score")
    posthoc = _load(path.parent / "posthoc_scientific_score.json")
    scored = _load(path.parent / "scored_report.json")
    if score is None and isinstance(posthoc, dict):
        score = posthoc.get("raw_scientific_score") or posthoc
    if score is None and isinstance(scored, dict):
        score = scored.get("raw_scientific_score") or scored.get("score")
    admission = report.get("canonical_admission")
    if isinstance(admission, dict):
        admission = admission.get("admitted")
    elif not isinstance(admission, bool):
        admission = report.get("provider_archive_admitted") if isinstance(report.get("provider_archive_admitted"), bool) else None
    # A response that never arrived has no schema or admission result; older
    # runners sometimes serialized both unavailable states as false.
    if payload is False:
        admission = None
    usage = {str(i + 1): a.get("usage") for i, a in enumerate(attempts) if a.get("usage")}
    latency = {str(i + 1): a.get("latency_ms") for i, a in enumerate(attempts) if a.get("latency_ms") is not None}
    sources = report.get("source_hashes") or {}
    if not isinstance(sources, dict):
        sources = {}
    for field in ("source_sha256", "article_sha256", "source_data_sha256", "gold_sha256"):
        if report.get(field):
            sources[field] = report[field]
    if isinstance(report.get("gold_assertions"), dict):
        sources["gold_assertion_count"] = len(report["gold_assertions"])
    repaired = report.get("repair_attempted")
    if repaired is None and attempts:
        repaired = any((a.get("repair_count") or a.get("schema_repair_count") or 0) > 0 for a in attempts)
    qualifying = next((value for key, value in report.items() if key.endswith("_live_gate_qualifying")), None)
    normalized = report.get("normalization_status") or report.get("normalization")
    if isinstance(normalized, (dict, list)):
        normalized = "reported_structured"
    return {
        "domain": domain, "case": report.get("case_id") or rel.parts[2],
        "provider": report.get("provider_name") or "gemini", "exact_model": model,
        "configured_model": report.get("configured_model_id") or report.get("requested_model"),
        "actual_model": report.get("actual_model") or report.get("provider_reported_model_id"),
        "provider_reported_model": report.get("provider_reported_model_id"),
        "run_id": report.get("run_id") or (rel.parts[-2] if "runs" in rel.parts else None),
        "report_path": rel.as_posix(), "report_sha256": _sha(path),
        "attempt_count": attempt_count, "payload_returned": payload,
        "raw_artifacts": raw_artifacts, "raw_artifact_sha256_coverage": len(raw_artifacts),
        "raw_scientific_score": _score(score) if payload else None,
        "schema_valid": report.get("schema_valid") if payload is not False else None,
        "repair_attempted": repaired,
        "normalization_status": normalized, "canonical_admission": admission,
        "deterministic_comparison": _score(report.get("deterministic_score") or report.get("deterministic_recovery_score") or report.get("post_recovery_score") or report.get("score")),
        "latency_ms_by_attempt": latency or None, "usage_by_attempt": usage or None,
        "provider_error_classes": errors,
        "source_gold_lock_identity": sources or None,
        "live_gate_qualifying": qualifying,
    }


def build() -> dict:
    runs = [_entry(path) for path in _report_paths()]
    runs.sort(key=lambda row: (row["domain"], row["case"], row["exact_model"] or "", row["run_id"] or "", row["report_path"]))
    matrix = {}
    for domain in sorted(set(row["domain"] for row in runs)):
        subset = [row for row in runs if row["domain"] == domain]
        matrix[domain] = {
            "runs": len(subset), "cases": sorted(set(row["case"] for row in subset)),
            "exact_models": sorted(set(row["exact_model"] for row in subset if row["exact_model"])),
            "payload_yes": sum(row["payload_returned"] is True for row in subset),
            "payload_no": sum(row["payload_returned"] is False for row in subset),
            "payload_unknown": sum(row["payload_returned"] is None for row in subset),
            "raw_sha_covered_runs": sum(bool(row["raw_artifacts"]) for row in subset),
            "schema_valid_yes": sum(row["schema_valid"] is True for row in subset),
            "schema_valid_no": sum(row["schema_valid"] is False for row in subset),
            "canonical_admitted": sum(row["canonical_admission"] is True for row in subset),
            "live_gate_qualifying": sum(row["live_gate_qualifying"] is True for row in subset),
            "error_classes": dict(Counter(code for row in subset for code in row["provider_error_classes"])),
        }
    return {"method": "metadata_only_from_existing_real_provider_reports", "model_merging": False,
            "no_payload_scoring": "null_not_zero", "runs": runs, "matrix": matrix}


if __name__ == "__main__":
    package = build()
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "provider_history.json").write_text(json.dumps({k: v for k, v in package.items() if k != "matrix"}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "provider_gate_matrix.json").write_text(json.dumps(package["matrix"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(package["runs"]), "runs", len(package["matrix"]), "domains")
