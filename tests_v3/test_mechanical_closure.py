from benchmark.mechanical_v1.closure_audit import build_closure_summary


def test_mechanical_v1_eight_case_closure_passes_exactly_30_invariants():
    summary = build_closure_summary()
    assert len(summary["cases"]) == 8
    assert summary["invariant_audit"] == {"passed": 30, "total": 30}
    assert summary["safety"]["ownership_contamination"] == 0
    assert summary["safety"]["evidence_violations"] == 0
    assert summary["safety"]["cross_record_leakage"] == 0
    assert summary["safety"]["analytics_contamination"] == 0
    assert summary["safety"]["compute_modalities"] == ["computational"]
    assert summary["freeze_decision"] == "READY_TO_FREEZE_DETERMINISTIC_MECHANICAL_V1"


def test_closure_does_not_report_one_heterogeneous_aggregate_percentage():
    summary = build_closure_summary()
    assert summary["aggregate_benchmark_score"] is None
    assert "No aggregate percentage" in summary["aggregate_score_policy"]


def test_provider_unavailability_is_not_scored_as_zero():
    summary = build_closure_summary()
    compute = next(item for item in summary["cases"] if item["case_id"] == "MECH-COMPUTE-F")
    assert compute["live_status"] == "LIVE_QUOTA_EXHAUSTED"
    assert compute["raw_provider_score"] is None
    assert compute["deterministic_recovery_score"] == {"passed": 28, "total": 28}
