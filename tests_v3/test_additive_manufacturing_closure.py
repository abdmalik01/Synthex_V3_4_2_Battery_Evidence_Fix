from __future__ import annotations

from benchmark.additive_manufacturing_v1.closure_audit import build_closure_audit


def test_eight_case_additive_manufacturing_v1_closure_is_freeze_ready():
    report = build_closure_audit()

    assert report["status"] == "PASS"
    assert report["case_count"] == 8
    assert report["passed_invariants"] == report["total_invariants"] == 30
    assert all(report["invariants"].values())
    assert report["provider_artifact_integrity"] is True
    assert report["ownership_contamination"] == 0
    assert report["evidence_violations"] == 0
    assert report["cross_record_leakage"] == 0
    assert report["analytics_contamination"] == 0
    assert report["mechanical_interoperability"] is True
    assert report["analytics_archive_safety"] is True
    assert report["freeze_decision"] == "READY_TO_FREEZE_DETERMINISTIC_AM_V1"
    assert report["raw_gemini_production_ready"] is False

    for case in report["cases"].values():
        assert case["offline_matches"] == case["offline_gold"]


def test_review_and_negative_controls_remain_noncanonical_at_closure():
    cases = build_closure_audit()["cases"]

    review = cases["AM-REVIEW-G"]
    assert review["route"] == "additive_manufacturing"
    assert review["experiments"] == review["calculations"] == review["outputs"] == 0
    assert review["quarantine_or_noncanonical_objects"] > 0

    negative = cases["AM-NEGATIVE-H"]
    assert negative["route"] == "batteries"
    assert negative["experiments"] == negative["calculations"] == negative["outputs"] == 0
