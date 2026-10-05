from benchmark.additive_manufacturing_v1.interim_audit import build_interim_audit


def test_six_case_interim_audit_passes_twenty_five_invariants():
    report = build_interim_audit()
    assert report["status"] == "PASS"
    assert len(report["cases"]) == 6
    assert report["passed_invariants"] == report["total_invariants"] == 25
    assert report["ownership_contamination"] == 0
    assert report["evidence_violations"] == 0
    assert report["cross_record_leakage"] == 0
