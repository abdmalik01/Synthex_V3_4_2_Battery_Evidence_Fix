from __future__ import annotations

import json
from pathlib import Path

from benchmark.photovoltaics_v1.audit_photovoltaics_v1 import audit_photovoltaics_v1
from benchmark.photovoltaics_v1.case_common import sha256
from benchmark.photovoltaics_v1.recover_spec_b import recover_spec_b
from benchmark.photovoltaics_v1.recover_stab_c import recover_stab_c
from benchmark.photovoltaics_v1.recover_stack_d import recover_stack_d
from benchmark.photovoltaics_v1.score_additional_cases import score_spec_b, score_stab_c, score_stack_d


CASE_DIR = Path(__file__).parents[1] / "benchmark" / "photovoltaics_v1"


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def test_pv_cases_bcd_sources_and_gold_were_locked_before_provider_calls():
    for name in ("spec_b_source_lock.json", "stab_c_source_lock.json", "stack_d_source_lock.json"):
        lock = _read(name)
        assert lock["locked_before_provider_call"] is True
        assert lock["provider_calls_at_lock"] == 0
        assert sha256(CASE_DIR / lock["gold_file"]) == lock["gold_sha256"]
    spec = _read("spec_b_source_lock.json")
    assert sha256(CASE_DIR / spec["article_file"]) == spec["article_sha256"]
    assert sha256(CASE_DIR / spec["source_data_file"]) == spec["source_data_sha256"]
    stab = _read("stab_c_source_lock.json")
    assert sha256(CASE_DIR / stab["article_file"]) == stab["article_sha256"]
    assert sha256(CASE_DIR / stab["supplement_zip_file"]) == stab["supplement_zip_sha256"]
    assert sha256(CASE_DIR / stab["supplement_file"]) == stab["supplement_sha256"]
    stack = _read("stack_d_source_lock.json")
    assert sha256(CASE_DIR / stack["source_file"]) == stack["source_sha256"]


def test_pv_spec_b_recovers_all_three_exact_workbook_series():
    gold = _read("spec_b_gold.json")
    archive, recovered = recover_spec_b()
    score = score_spec_b(archive, gold)
    assert score["passed"] == score["total"] == 3
    assert score["devices"] == score["experiments"] == 3
    assert score["outputs"] == score["analytics_rows"] == 223
    assert [len(item["points"]) for item in recovered] == [71, 81, 71]
    assert score["scientific_safety"]["quarantine_count"] == 0


def test_pv_stab_c_keeps_six_variants_protocol_and_lower_bound_distinct():
    gold = _read("stab_c_gold.json")
    archive, recovered = recover_stab_c()
    score = score_stab_c(archive, gold)
    assert score["passed"] == score["total"] == 6
    assert score["devices"] == score["experiments"] == 6
    assert score["outputs"] == score["analytics_rows"] == 7
    assert next(item for item in recovered if item["variant"] == "ma_over_sealing")["qualifier"] == "lower_bound"
    assert score["scientific_safety"]["initial_reference_and_aged_state_preserved"] is True
    assert score["scientific_safety"]["quarantine_count"] == 0


def test_pv_stack_d_keeps_six_stacks_process_variants_and_24_outputs():
    gold = _read("stack_d_gold.json")
    archive, recovered = recover_stack_d()
    score = score_stack_d(archive, gold)
    assert recovered == gold["variants"]
    assert score["passed"] == score["total"] == 6
    assert score["devices"] == score["processes"] == score["experiments"] == 6
    assert score["outputs"] == score["analytics_rows"] == 24
    assert score["scientific_safety"]["quarantine_count"] == 0


def test_photovoltaics_v1_four_case_audit_passes_exactly_25_invariants():
    audit = audit_photovoltaics_v1()
    assert audit["passed"] == audit["total"] == 25
    assert audit["failed"] == []
    assert audit["contamination"] == {
        "ownership_contamination": 0,
        "evidence_violations": 0,
        "cross_record_leakage": 0,
        "analytics_contamination": 0,
    }
