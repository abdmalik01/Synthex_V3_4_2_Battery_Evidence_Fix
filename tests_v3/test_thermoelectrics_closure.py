from __future__ import annotations

import hashlib
import json

import pytest

from benchmark.thermoelectrics_v1.closure_audit import build_closure_audit
from benchmark.thermoelectrics_v1.build_freeze_manifest import build_manifest
from benchmark.thermoelectrics_v1.recover_closure import CASE_DIR
from benchmark.thermoelectrics_v1.recover_gold_a import supplementary_local_status
from benchmark.thermoelectrics_v1.run_closure_offline import build_reports


@pytest.fixture(scope="module")
def audit() -> dict:
    return build_closure_audit()


def test_all_four_closure_cases_pass_provider_free():
    reports = build_reports()
    assert set(reports) == {"TE-COMPUTE-E", "TE-REVIEW-F", "TE-NEG-G", "TE-MIXED-H"}
    assert all(report["passed"] for report in reports.values())
    assert reports["TE-COMPUTE-E"]["outputs"] == 30
    assert reports["TE-REVIEW-F"]["quarantine"] == 42
    assert reports["TE-NEG-G"]["route"] == "photovoltaics"
    assert reports["TE-MIXED-H"]["modality_split_preserved"]


def test_all_eight_cases_and_40_invariants_close(audit):
    assert audit["case_count"] == 8
    assert all(report["passed"] for report in audit["cases"].values())
    assert audit["totals"] == {
        "canonical_outputs": 428,
        "experimental_outputs": 396,
        "computational_outputs": 32,
        "analytics_rows": 428,
        "experiments": 23,
        "calculations": 6,
        "review_noncanonical_values": 21,
    }
    assert len(audit["invariants"]) == 40
    assert audit["invariant_summary"] == {"passed": 40, "total": 40, "all_passed": True}
    assert audit["contamination"] == {
        "ownership": 0, "evidence_violations": 0,
        "cross_record_leakage": 0, "analytics": 0,
    }
    assert audit["passed"]


def test_closure_source_and_gold_locks_are_exact(audit):
    for lock in audit["source_locks"].values():
        assert lock["locked_before_provider_run"] is True
        gold = CASE_DIR / lock["gold_file"]
        assert hashlib.sha256(gold.read_bytes()).hexdigest() == lock["gold_sha256"]
        for key, expected in lock.items():
            if not key.endswith("_sha256") or key == "gold_sha256":
                continue
            path_key = key.removesuffix("_sha256")
            if path_key not in lock and f"{path_key}_file" in lock:
                path_key = f"{path_key}_file"
            if lock["case_id"] == "TE-GOLD-A" and key == "supplementary_file_sha256":
                assert expected == "7f3f950c6e2385622056cfd49481edca38cd0e40234f2dc3ef84dc112a9d05de"
                assert supplementary_local_status(lock) in {"verified_local", "not_available_locally"}
                continue
            assert hashlib.sha256((CASE_DIR / lock[path_key]).read_bytes()).hexdigest() == expected


def test_checked_in_machine_readable_audit_matches_current_closure(audit):
    persisted = json.loads((CASE_DIR / "closure_audit.json").read_text(encoding="utf-8"))
    assert persisted["schema"] == "synthex.thermoelectrics.closure.v1"
    assert persisted["cases"] == audit["cases"]
    assert persisted["invariants"] == audit["invariants"]
    assert persisted["contamination"] == audit["contamination"]
    assert persisted["passed"] is True


def test_freeze_manifest_requires_and_records_real_scored_gemini_payload():
    manifest = build_manifest()
    persisted = json.loads((CASE_DIR / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest == persisted
    assert manifest["freeze_status"] == "FROZEN_DETERMINISTIC_PROVIDER_EVALUATION_MODEL_SPECIFIC"
    assert manifest["provider_architecture"] == {
        "active_live_provider": "gemini",
        "openai_state": "FUTURE_SUPPORTED_BUT_INACTIVE",
        "provider_neutral_core_preserved": True,
        "silent_fallback": False,
    }
    gate = manifest["live_gate"]
    assert gate["satisfied"] is True
    assert gate["provider_name"] == "gemini"
    assert gate["model_id"] == "models/gemini-3.1-flash-lite"
    assert gate["payload_persisted_before_validation"] is True
    assert gate["scientifically_scored"] is True
    assert gate["canonical_admitted"] is False
    assert len(gate["raw_response_sha256"]) == 64
    assert any(
        item["run_id"] == gate["run_id"] and item["payload_returned"]
        and item["scientifically_scored"] and item["raw_scientific_score"]["total_exact_points"] == 5
        for item in manifest["provider_history"]
    )
