from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "benchmark/photovoltaics_v1"
MANIFEST = json.loads((CASE / "freeze_manifest.json").read_text(encoding="utf-8"))


def test_pv_freeze_manifest_closes_eight_cases_and_35_invariants():
    assert MANIFEST["freeze_status"] == "FROZEN_DETERMINISTIC_PROVIDER_EVALUATION_MODEL_SPECIFIC"
    assert len(MANIFEST["cases"]) == 8
    assert MANIFEST["closure"]["case_assertions"] == {"passed": 57, "total": 57}
    assert MANIFEST["closure"]["scientific_invariants"] == {"passed": 35, "total": 35}
    assert all(MANIFEST["closure"][key] == 0 for key in (
        "ownership_contamination", "evidence_violations",
        "cross_record_leakage", "analytics_contamination",
    ))


def test_pv_freeze_manifest_source_and_gold_hashes_match_locks():
    for lock_name in (
        "source_lock.json", "spec_b_source_lock.json", "stab_c_source_lock.json",
        "stack_d_source_lock.json", "compute_e_source_lock.json", "review_f_source_lock.json",
        "negative_g_source_lock.json", "mixed_h_source_lock.json",
    ):
        lock = json.loads((CASE / lock_name).read_text(encoding="utf-8"))
        if "source_file" in lock:
            assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
        assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_pv_freeze_gate_preserves_history_and_requires_real_scored_payload():
    gate = MANIFEST["live_gate"]
    assert gate["satisfied"] is True
    assert gate["model_id"] != "gemini-3.5-flash"
    assert gate["payload_persisted_before_validation"] is True
    assert gate["scientifically_scored"] is True
    history = MANIFEST["provider_history"]
    historical = [item for item in history if item["history"] == "historical"]
    assert len(historical) == 2
    assert all(item["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES" for item in historical)
    qualifying = next(item for item in history if item.get("run_id") == gate["run_id"])
    assert qualifying["payload_returned"] is True
    assert qualifying["raw_scores"]
    assert qualifying["canonical_admitted"] is False
