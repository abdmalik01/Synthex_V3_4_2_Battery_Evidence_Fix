from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
BENCHMARK = REPO_ROOT / "benchmark" / "corrosion_v1"


def _load(name: str):
    return json.loads((BENCHMARK / name).read_text(encoding="utf-8"))


def test_corrosion_freeze_has_eight_locked_cases_with_matching_checksums():
    freeze = _load("freeze_manifest.json")
    lock = _load("corpus_lock.json")
    locked = {item["id"]: item for item in lock["files"]}

    assert freeze["domain"] == "corrosion"
    assert freeze["benchmark_stage"] == "corrosion_v1_stage3_frozen"
    assert freeze["case_count"] == len(freeze["cases"]) == 8
    assert len({item["id"] for item in freeze["cases"]}) == 8
    assert all(item["id"] in locked for item in freeze["cases"])
    assert all(
        item["source_sha256"] == locked[item["id"]]["sha256"]
        for item in freeze["cases"]
    )


def test_corrosion_freeze_preserves_live_and_offline_status_semantics():
    cases = {item["id"]: item for item in _load("freeze_manifest.json")["cases"]}

    assert cases["CORR-WEIGHT-E"]["closure_status"] == "RAW_PROVIDER_FAILED_BUT_RECOVERY_PASSED"
    assert cases["CORR-WEIGHT-E"]["historical_raw_provider_overall"] == 0.0
    assert cases["CORR-WEIGHT-E"]["offline_assertions"] == "4/4"
    assert cases["CORR-DFT-F"]["closure_status"] == "LIVE_UNAVAILABLE"
    assert cases["CORR-DFT-F"]["live_provider_score"] is None
    assert cases["CORR-DFT-F"]["offline_assertions"] == "27/27"
    assert cases["CORR-REVIEW-G"]["closure_status"] == "PASS_OFFLINE"
    assert cases["CORR-NEGATIVE-H"]["expected_route"] == "batteries"


def test_corrosion_freeze_records_all_scientific_invariants_and_zero_contamination():
    freeze = _load("freeze_manifest.json")

    assert len(freeze["scientific_invariants"]) == 20
    assert len(set(freeze["scientific_invariants"])) == 20
    assert freeze["expected_contamination"] == {
        "ownership": 0,
        "evidence": 0,
        "cross_record_leakage": 0,
        "archive_analytics": 0,
    }
    assert freeze["test_baseline"]["corrosion_passed"] == 103
    assert freeze["reproduce"]["closure_audit"].endswith("audit_closure.py")
