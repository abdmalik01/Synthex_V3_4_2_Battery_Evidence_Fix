from __future__ import annotations

import pytest

from benchmark.mechanical_v1.interim_audit import build_interim_summary


@pytest.fixture(scope="module")
def summary():
    return build_interim_summary()


def test_all_twenty_cross_case_invariants_pass(summary):
    assert [item["id"] for item in summary["invariants"]] == list(range(1, 21))
    assert all(item["passed"] for item in summary["invariants"])
    assert summary["invariant_audit"] == {"passed": 20, "total": 20}


def test_interim_summary_avoids_heterogeneous_aggregate_score(summary):
    assert summary["aggregate_benchmark_score"] is None
    assert len(summary["cases"]) == 5
    assert {item["case_id"] for item in summary["cases"]} == {
        "MECH-GOLD-A", "MECH-CREEP-B", "MECH-FATIGUE-C", "MECH-HARD-D", "MECH-FRACTURE-E",
    }
    assert all(item["offline"]["passed"] == item["offline"]["total"] for item in summary["cases"])


def test_interim_summary_reports_no_canonical_contamination(summary):
    assert summary["safety"]["ownership_contamination"] == 0
    assert summary["safety"]["evidence_violations"] == 0
    assert summary["safety"]["cross_record_leakage"] == 0
    assert summary["safety"]["excluded_creep_na_rows"] == 3
