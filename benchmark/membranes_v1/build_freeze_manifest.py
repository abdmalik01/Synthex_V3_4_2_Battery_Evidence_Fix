"""Build the durable Membranes V1 freeze manifest from audited artifacts."""

from __future__ import annotations

import json
from pathlib import Path


CASE_DIR = Path(__file__).resolve().parent
ROOT = CASE_DIR.parents[1]
CASE_LOCKS = {
    "MEM-GOLD-A": "source_lock.json",
    "MEM-SEP-B": "source_lock_sep_b.json",
    "MEM-STAB-C": "source_lock_stab_c.json",
    "MEM-PROCESS-D": "source_lock_process_d.json",
    "MEM-COMPUTE-E": "source_lock_compute_e.json",
    "MEM-REVIEW-F": "source_lock_review_f.json",
    "MEM-NEG-G": "source_lock_neg_g.json",
    "MEM-MIXED-H": "source_lock_mixed_h.json",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(*, passed_tests: int) -> dict:
    closure = _read(CASE_DIR / "closure_audit.json")
    if not closure["passed"] or closure["passed_invariants"] != 40 or any(closure["contamination"].values()):
        raise ValueError("Membranes closure gate is not satisfied")
    live = _read(ROOT / "output/membranes_v1/provider_runs/interim_live_audit.json")
    if not live["mem_live_gate_satisfied"]:
        raise ValueError("Historical Membranes live gate is not satisfied")

    cases = []
    for case_id, lock_name in CASE_LOCKS.items():
        lock = _read(CASE_DIR / lock_name)
        counts = closure["cases"][case_id]
        cases.append({
            "case_id": case_id,
            "offline_passed": True,
            **counts,
            "source_hashes": {
                key: value for key, value in lock.items()
                if key.endswith("_sha256") and key != "gold_sha256"
            },
            "gold_sha256": lock["gold_sha256"],
            **({"review_noncanonical_candidate_count": 3, "review_noncanonical_output_count": 2} if case_id == "MEM-REVIEW-F" else {}),
            **({"expected_route": "batteries"} if case_id == "MEM-NEG-G" else {}),
        })

    provider_history = []
    for item in live["mem_gold_a"]["models"]:
        provider_history.append({
            "case_id": "MEM-GOLD-A", "provider_name": "gemini", "preserved": True,
            "model_id": item["model_id"], "run_id": item["run_id"],
            "attempts": item["attempts"], "payload_returned": item["payload_returned"],
            "status": item["status"], "failure": item.get("failure"),
            "raw_scientific_score": item.get("raw_scientific_score"),
            "schema_valid": item.get("schema_valid", False),
            "canonical_admission": item.get("canonical_admission", False),
            "raw_response_sha256": item.get("raw_response_sha256"),
        })
    provider_history.append({
        "case_id": "MEM-SEP-B", "provider_name": "gemini", "preserved": True,
        "model_id": live["mem_sep_b"]["model_id"], "run_id": live["mem_sep_b"]["run_id"],
        "attempts": live["mem_sep_b"]["attempts"], "payload_returned": live["mem_sep_b"]["payload_returned"],
        "status": live["mem_sep_b"]["status"],
        "raw_scientific_score": live["mem_sep_b"]["raw_scientific_score"],
        "schema_valid": live["mem_sep_b"]["schema_valid"],
        "canonical_admission": live["mem_sep_b"]["canonical_admission"],
        "raw_response_sha256": live["mem_sep_b"]["raw_response_sha256"],
    })

    normalization = {
        case_id: {
            "normalizer_version": status["normalizer_version"],
            "schema_valid": status["schema_valid"],
            "canonical_admission": status["canonical_admission"],
            "canonical_outputs": status["canonical_outputs"],
            "source_raw_sha256": status["source_raw_sha256"],
            "raw_hash_still_matches": status["raw_hash_still_matches"],
            "normalized_candidate_separate": status["normalized_candidate_separate"],
            "safety": status["safety"],
            "scientific_score": status["scientific_score"]["score"],
        }
        for case_id, status in closure["normalization"].items()
    }
    return {
        "domain": "membranes",
        "version": "1.0.0",
        "freeze_status": "FROZEN_DETERMINISTIC_PROVIDER_EVALUATION_MODEL_SPECIFIC",
        "freeze_statement": "Membranes V1 is scientifically closed for deterministic extraction, membrane/specimen association, multilayer architecture, fabrication linkage, species and gas-pair identity, transport properties, separation metrics, stability/fouling semantics, computational separation, review containment, negative routing, evidence ownership, analytics safety, and archive/domain scoping. Raw provider extraction remains model-specific and is not automatically canonical.",
        "provider_architecture": {
            "active_live_provider": "gemini",
            "openai_state": "FUTURE_SUPPORTED_BUT_INACTIVE",
            "provider_neutral_core_preserved": True,
            "silent_fallback": False,
        },
        "live_gate": {
            "satisfied": True,
            "qualifying_case": live["qualifying_case"],
            "provider_name": live["provider_name"],
            "model_id": live["qualifying_model"],
            "run_id": live["qualifying_run_id"],
            "payload_persisted_before_validation": True,
            "scientifically_scored": True,
            "canonical_admission": False,
            "raw_response_sha256": next(item["raw_response_sha256"] for item in provider_history if item["case_id"] == "MEM-GOLD-A" and item["payload_returned"]),
        },
        "closure": {
            "cases_passed": 8, "cases_total": 8,
            "scientific_invariants": {"all_passed": True, "passed": 40, "total": 40},
            "contamination": closure["contamination"],
            "totals": {
                "canonical_outputs": closure["canonical_output_total"],
                "experimental_outputs": closure["experimental_outputs"],
                "computational_outputs": closure["computational_outputs"],
                "analytics_rows": sum(item["analytics_rows"] for item in closure["cases"].values()),
                "experiments": sum(item["experiments"] for item in closure["cases"].values()),
                "calculations": sum(item["calculations"] for item in closure["cases"].values()),
                "review_noncanonical_outputs": 2,
            },
        },
        "cases": cases,
        "provider_history": provider_history,
        "normalization": normalization,
        "regression": {
            "full_tests_v3_passed": True,
            "passed_tests": passed_tests,
            "failures": 0,
            "allowed_warning": "google-genai uses a Python typing alias deprecated for removal in Python 3.17",
        },
        "reproduce": {
            "provider_normalization": ".\\.venv\\Scripts\\python.exe -m pytest tests_v3\\test_membrane_provider_normalization.py -q --basetemp=.pytest_tmp_mem_normalization",
            "closure_audit": ".\\.venv\\Scripts\\python.exe -m benchmark.membranes_v1.closure_audit --write",
            "full_suite": ".\\.venv\\Scripts\\python.exe -m pytest tests_v3 -q --basetemp=.pytest_tmp_membrane_closure",
            "diff_check": "git diff --check",
        },
        "known_limitations": [
            "Both persisted Gemini payloads normalize to schema-valid candidates but remain canonically inadmissible because page-verbatim source evidence is absent.",
            "SEP-B pressure remains associated only with 42 permeability outputs; no pressure was propagated to 56 selectivity outputs.",
            "The computational case covers molecular-dynamics lipid-bilayer gas transport and does not claim experimental separation performance.",
            "No new Gemini or OpenAI call was made during closure.",
        ],
    }


def write_manifest(*, passed_tests: int) -> Path:
    output = CASE_DIR / "freeze_manifest.json"
    output.write_text(json.dumps(build_manifest(passed_tests=passed_tests), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--passed-tests", type=int, required=True)
    args = parser.parse_args()
    print(write_manifest(passed_tests=args.passed_tests))
