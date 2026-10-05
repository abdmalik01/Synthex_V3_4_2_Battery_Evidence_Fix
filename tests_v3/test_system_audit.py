from hashlib import sha256
import json

from benchmark.system_audit import build as audit_build
from benchmark.system_audit.build import (
    classification, closure_values, enrich_frozen_normalization_runs,
    lock_hash_audit, measure,
    provider_group_summary, safety_dimensions,
)


def test_rates_keep_empty_denominators_unavailable():
    assert measure(0, 0) == {"numerator": 0, "denominator": 0, "rate": None}
    assert measure(2, 5)["rate"] == 0.4


def test_domain_totals_require_complete_case_coverage():
    freeze = {"cases": [
        {"case_id": "A", "outputs": 3, "experiments": 1, "calculations": 0},
        {"case_id": "B", "outputs": 0, "experiments": 0, "calculations": 0},
    ]}
    assert closure_values(freeze, {})[:3] == (3, 1, 0)
    del freeze["cases"][1]["outputs"]
    assert closure_values(freeze, {})[0] is None


def test_worktree_classification_keeps_pending_biomaterials_separate():
    assert classification("benchmark/biomaterials_v1/gold_a.json") == "B_biomaterials_pending_freeze"
    assert classification("benchmark/corrosion_v1/retry_dft_f.py") == "E_corrosion_historical_work"
    assert classification("tmp/render/page.png") == "G_pytest_temp_artifacts"


def test_safety_dimensions_do_not_turn_unreported_metrics_into_zero():
    dimensions = safety_dimensions({
        "new": {"reported": {"ownership_contamination": []}, "basis_kind": "closure_observed"},
        "legacy": {"reported": None, "basis_kind": "freeze_manifest_claim_or_expected"},
    })
    assert dimensions["ownership_contamination"]["new"]["value"] == 0
    assert dimensions["ownership_contamination"]["legacy"]["value"] is None
    assert dimensions["review_leakage"]["new"]["value"] is None


def test_provider_summary_excludes_unavailable_runs_from_scientific_denominators():
    summary = provider_group_summary([
        {"case": "A", "exact_model": "m1", "attempt_count": 3, "payload_returned": False,
         "raw_scientific_score": None, "schema_valid": None, "canonical_admission": None},
        {"case": "A", "exact_model": "m2", "attempt_count": 1, "payload_returned": True,
         "raw_scientific_score": {"passed": 1, "total": 2}, "schema_valid": False,
         "canonical_admission": False},
    ])
    assert summary["payload_availability"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["schema_validity_observed"]["denominator"] == 1
    assert summary["canonical_admission_observed"]["denominator"] == 1
    assert summary["raw_scientifically_scored_payload_runs"] == 1
    assert summary["normalized_schema_validity_observed"]["rate"] is None


def test_source_lock_audit_reports_unresolved_references(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_build, "ROOT", tmp_path)
    good = sha256(b"locked source").hexdigest()
    missing = sha256(b"missing source").hexdigest()
    (tmp_path / "source_lock.json").write_text(
        json.dumps({"source_sha256": good, "nested": {"gold_sha256": missing}}),
        encoding="utf-8",
    )
    result = lock_hash_audit(tmp_path, {good: ["benchmark/source.pdf"]})
    assert result["verified_hash_references"] == 1
    assert [(row["field"], row["sha256"]) for row in result["unresolved_hash_references"]] == [("gold_sha256", missing)]


def test_normalized_scores_join_only_the_exact_frozen_run():
    runs = [
        {"case": "SEM-GOLD-A", "run_id": "r1", "exact_model": "models/m1"},
        {"case": "SEM-GOLD-A", "run_id": "r1", "exact_model": "models/m2"},
    ]
    manifest = {"provider_runs": [{
        "case_id": "SEM-GOLD-A", "run_id": "r1", "exact_model": "models/m1",
        "normalized_scientific_score": {"exact_value_and_unit_points": 2, "expected_points": 4},
        "normalized_schema_valid": True, "normalized_canonical_admission": False,
    }]}
    enrich_frozen_normalization_runs(runs, manifest)
    assert runs[0]["normalized_scientific_score"]["exact_value_and_unit_points"] == 2
    assert runs[0]["normalized_canonical_admission"] is False
    assert "normalized_scientific_score" not in runs[1]
