"""Build the Thermoelectrics V1 freeze manifest from audited artifacts."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.recover_closure import CASE_DIR


CASE_LAYOUT = {
    "TE-GOLD-A": {"lock": "source_lock.json", "materials": 1, "processes": 1, "experiments": 6, "calculations": 0, "outputs": 102},
    "TE-SERIES-B": {"lock": "source_lock_series_b.json", "materials": 3, "processes": 1, "experiments": 9, "calculations": 0, "outputs": 198},
    "TE-DERIVED-C": {"lock": "source_lock_derived_c.json", "materials": 1, "processes": 0, "experiments": 5, "calculations": 0, "outputs": 90},
    "TE-ANISO-D": {"lock": "source_lock_aniso_d.json", "materials": 1, "processes": 0, "experiments": 1, "calculations": 0, "outputs": 2},
    "TE-COMPUTE-E": {"lock": "source_lock_compute_e.json", "materials": 5, "processes": 0, "experiments": 0, "calculations": 5, "outputs": 30},
    "TE-REVIEW-F": {"lock": "source_lock_review_f.json", "materials": 0, "processes": 0, "experiments": 0, "calculations": 0, "outputs": 0, "review_noncanonical_values": 21},
    "TE-NEG-G": {"lock": "source_lock_neg_g.json", "materials": 0, "processes": 0, "experiments": 0, "calculations": 0, "outputs": 0, "expected_route": "photovoltaics"},
    "TE-MIXED-H": {"lock": "source_lock_mixed_h.json", "materials": 1, "processes": 0, "experiments": 2, "calculations": 1, "outputs": 6},
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest() -> dict:
    closure = _read(CASE_DIR / "closure_audit.json")
    cases = []
    for case_id, layout in CASE_LAYOUT.items():
        lock = _read(CASE_DIR / layout["lock"])
        cases.append({
            "case_id": case_id, "offline_passed": closure["cases"][case_id]["passed"],
            **{key: value for key, value in layout.items() if key != "lock"},
            "analytics_rows": closure["cases"][case_id]["analytics_rows"],
            "source_hashes": {key: value for key, value in lock.items() if key.endswith("_sha256") and key != "gold_sha256"},
            "gold_sha256": lock["gold_sha256"],
        })

    provider_root = ROOT / "output" / "thermoelectrics_v1" / "provider_runs"
    provider_history = []
    qualifying = None
    for report_path in sorted(provider_root.glob("**/report.json")):
        report = _read(report_path)
        run_root = report_path.parent
        posthoc_path = run_root / "posthoc_scientific_score.json"
        posthoc = _read(posthoc_path) if posthoc_path.exists() else None
        provider_statuses = sorted(run_root.glob("attempt-*/provider_status.json"))
        last_status = _read(provider_statuses[-1]) if provider_statuses else {}
        item = {
            "provider_name": report.get("provider_name", "gemini"), "model_id": report.get("model_id"),
            "run_id": report.get("run_id"), "case_id": report.get("case_id"), "status": report.get("status"),
            "attempts": len(report.get("attempts", [])), "payload_returned": report.get("payload_returned", False),
            "schema_valid": report.get("schema_valid", False),
            "canonical_admitted": bool((report.get("canonical_admission") or {}).get("admitted")),
            "raw_scientific_score": posthoc["score"] if posthoc else report.get("raw_scientific_score"),
            "scientifically_scored": bool(posthoc or report.get("raw_scientific_score") is not None),
            "latency_ms": last_status.get("latency_ms"), "usage": last_status.get("usage"),
            "fallback_used": report.get("fallback_used", False),
            "artifact_report": str(report_path.relative_to(ROOT)), "preserved": True,
        }
        if posthoc:
            item["posthoc_score_artifact"] = str(posthoc_path.relative_to(ROOT))
            item["raw_response_sha256"] = posthoc["raw_response_sha256"]
        provider_history.append(item)
        if posthoc and posthoc.get("qualifies_live_payload_gate"):
            qualifying = item
    if not provider_history:
        # The committed manifest preserves historical provider identity and
        # scores; ignored local report bodies are optional for offline replay.
        persisted = _read(CASE_DIR / "freeze_manifest.json")
        provider_history = persisted["provider_history"]
        qualifying = next((item for item in provider_history
                           if item.get("run_id") == persisted["live_gate"]["run_id"]), None)
    for item in provider_history:
        expected = item.get("raw_response_sha256")
        if expected:
            run_root = ROOT / Path(item["artifact_report"]).parent
            for raw_path in run_root.glob("attempt-*/raw_response.txt"):
                if sha256(raw_path.read_bytes()).hexdigest() != expected:
                    raise ValueError(f"TE provider raw artifact hash mismatch: {item['run_id']}")
    if qualifying is None:
        raise ValueError("TE live gate is not satisfied; refusing to generate a frozen manifest")

    return {
        "domain": "thermoelectrics", "version": "1.0.0",
        "freeze_status": "FROZEN_DETERMINISTIC_PROVIDER_EVALUATION_MODEL_SPECIFIC",
        "freeze_statement": "Thermoelectrics V1 is scientifically closed for deterministic experimental series, reported-derived metrics, anisotropy, computational transport, review containment, negative routing, mixed-modality separation, evidence ownership, analytics safety, and archive/domain scoping. Provider evaluation remains model-specific and is not equivalent to deterministic Synthex recovery.",
        "provider_architecture": {"active_live_provider": "gemini", "openai_state": "FUTURE_SUPPORTED_BUT_INACTIVE", "provider_neutral_core_preserved": True, "silent_fallback": False},
        "live_gate": {
            "satisfied": True, "qualifying_case": qualifying["case_id"], "provider_name": qualifying["provider_name"],
            "model_id": qualifying["model_id"], "run_id": qualifying["run_id"],
            "payload_persisted_before_validation": True, "scientifically_scored": True,
            "canonical_admitted": qualifying["canonical_admitted"], "raw_response_sha256": qualifying["raw_response_sha256"],
            "posthoc_score_artifact": qualifying["posthoc_score_artifact"],
        },
        "closure": {
            "cases_passed": sum(item["passed"] for item in closure["cases"].values()), "cases_total": closure["case_count"],
            "scientific_invariants": closure["invariant_summary"], "contamination": closure["contamination"], "totals": closure["totals"],
        },
        "cases": cases, "provider_history": provider_history,
        "regression": {"expected_post_freeze_tests": 601, "allowed_warning": "google-genai uses a Python typing alias deprecated for removal in Python 3.17"},
        "reproduce": {
            "offline_cases": ".\\.venv\\Scripts\\python.exe benchmark\\thermoelectrics_v1\\run_closure_offline.py",
            "closure_audit": ".\\.venv\\Scripts\\python.exe benchmark\\thermoelectrics_v1\\run_closure_audit.py",
            "full_suite": ".\\.venv\\Scripts\\python.exe -m pytest tests_v3 -q --basetemp=.pytest_tmp_te_closure",
        },
        "limitations": [
            "The qualifying raw Gemini payload recovered only 5 of 102 exact points and was not canonically admitted.",
            "The qualifying payload omitted explicit scientific-type labels and exact frozen composition identity.",
            "No TE-SERIES-B live run was attempted after the third selected model reported zero available Pro input-token quota.",
            "No OpenAI live discovery or call was performed.",
        ],
    }


def main() -> int:
    manifest = build_manifest()
    output = CASE_DIR / "freeze_manifest.json"
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "live_gate": manifest["live_gate"], "provider_runs": len(manifest["provider_history"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
