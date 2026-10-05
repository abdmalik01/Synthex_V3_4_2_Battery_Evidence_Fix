from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmark.mechanical_v1.closure_audit import build_closure_summary


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "benchmark" / "mechanical_v1"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mechanical_freeze_manifest_matches_locked_sources_gold_and_closure():
    manifest = _read(CASE_DIR / "freeze_manifest.json")
    closure = build_closure_summary()
    closure_cases = {item["case_id"]: item for item in closure["cases"]}
    gold_paths = {
        "MECH-GOLD-A": CASE_DIR / "gold_a_contract.json",
        "MECH-CREEP-B": CASE_DIR / "creep_b_gold.json",
        "MECH-FATIGUE-C": CASE_DIR / "fatigue_c_gold.json",
        "MECH-HARD-D": CASE_DIR / "hard_d_gold.json",
        "MECH-FRACTURE-E": CASE_DIR / "fracture_e_gold.json",
        "MECH-COMPUTE-F": CASE_DIR / "compute_f_gold.json",
        "MECH-REVIEW-G": CASE_DIR / "review_g_gold.json",
        "MECH-NEGATIVE-H": CASE_DIR / "negative_h_gold.json",
    }

    assert manifest["archive_schema_version"] == "3.4.0"
    assert manifest["software_version"] == "3.4.2"
    assert manifest["test_baseline"]["pre_freeze_full_suite_passed"] == 445
    assert manifest["test_baseline"]["post_freeze_full_suite_passed"] == 446
    assert manifest["freeze_decision"] == closure["freeze_decision"]
    assert manifest["case_count"] == len(closure_cases) == 8
    assert manifest["scientific_invariant_count"] == 30
    assert manifest["scientific_invariants_passed"] == closure["invariant_audit"]["passed"] == 30
    assert manifest["scientific_invariants"] == [item["name"] for item in closure["invariants"]]

    for case in manifest["cases"]:
        closure_case = closure_cases[case["id"]]
        assert case["source_sha256"] == closure_case["source_checksum"]
        assert case["gold_sha256"] == _sha256(gold_paths[case["id"]])
        assert case["live_status"] == closure_case["live_status"]
        recovery = closure_case["deterministic_recovery_score"]
        assert case["deterministic_recovery_score"] == f'{recovery["passed"]}/{recovery["total"]}'
        raw = closure_case["raw_provider_score"]
        assert case["raw_provider_score"] == (None if raw is None else f'{raw["passed"]}/{raw["total"]}')
        assert case["closure_status"] == closure_case["status"]
        assert case["canonical_counts"] == {
            "experiments": closure_case["experiments"],
            "calculations": closure_case["calculations"],
            "outputs": closure_case["outputs"],
        }
        assert case["quarantine_noncanonical_count"] == closure_case["quarantine_noncanonical_count"]
