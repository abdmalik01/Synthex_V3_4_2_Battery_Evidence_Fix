from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.closure_audit import build_closure_audit
from synthex_platform.version import __version__


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "benchmark/additive_manufacturing_v1"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_am_freeze_manifest_matches_locks_gold_and_live_closure():
    manifest = _read(CASE_DIR / "freeze_manifest.json")
    closure = build_closure_audit()
    gold_paths = {
        "AM-GOLD-A": CASE_DIR / "gold_a_contract.json",
        "AM-DENS-B": CASE_DIR / "dens_b_gold.json",
        "AM-MICRO-C": CASE_DIR / "micro_c_gold.json",
        "AM-MECH-D": CASE_DIR / "mech_d_gold.json",
        "AM-POST-E": CASE_DIR / "post_e_gold.json",
        "AM-COMPUTE-F": CASE_DIR / "compute_f_gold.json",
        "AM-REVIEW-G": CASE_DIR / "review_g_gold.json",
        "AM-NEGATIVE-H": CASE_DIR / "negative_h_gold.json",
    }

    assert manifest["software_version"] == __version__ == "3.4.2"
    assert manifest["archive_schema_version"] == "3.4.0"
    assert manifest["domain_manifest_version"] == "1.2.0"
    assert manifest["raw_provider_readiness"] == "NOT_PRODUCTION_READY"
    assert manifest["freeze_decision"] == closure["freeze_decision"]
    assert manifest["case_count"] == closure["case_count"] == 8
    assert manifest["scientific_invariant_count"] == len(closure["invariants"]) == 30
    assert manifest["scientific_invariants_passed"] == closure["passed_invariants"] == 30
    assert manifest["scientific_invariants"] == list(closure["invariants"])
    assert all(closure["invariants"].values())

    for case in manifest["cases"]:
        actual = closure["cases"][case["id"]]
        assert case["source_sha256"] == actual["source_sha256"]
        assert case["gold_sha256"] == actual["gold_sha256"] == _sha256(gold_paths[case["id"]])
        assert case["offline_score"] == f'{actual["offline_matches"]}/{actual["offline_gold"]}'
        expected_provider = "PASS_OFFLINE" if actual["live_status"] == "NOT_RUN" else actual["live_status"]
        assert case["provider_state"] == expected_provider
        assert case["canonical_admission"] == actual["canonical_admission_result"]
        assert case["deterministic_result"] == (
            f'{actual["deterministic_result"]["passed"]}/'
            f'{actual["deterministic_result"]["total"]}'
        )
        assert case["canonical_counts"] == {
            "experiments": actual["experiments"],
            "calculations": actual["calculations"],
            "outputs": actual["outputs"],
        }
        assert case["quarantine_noncanonical_count"] == actual["quarantine_or_noncanonical_objects"]
        assert case["closure_status"] == actual["status"]

    assert manifest["expected_contamination"] == {
        "ownership": closure["ownership_contamination"],
        "evidence": closure["evidence_violations"],
        "cross_record_leakage": closure["cross_record_leakage"],
        "archive_analytics": closure["analytics_contamination"],
    }
