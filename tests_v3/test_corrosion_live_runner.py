from pathlib import Path
import json

import pytest

from synthex_platform.benchmarks.corrosion_live import (
    HOLDOUT_CASE_ID,
    build_live_pipeline,
    diagnose_live_output,
    expectations_from_gold,
    load_live_case,
)


REPO_ROOT = Path(__file__).parents[1]


def test_live_corrosion_gold_a_resolves_locked_pdf_and_manual_gold():
    case = load_live_case("CORR-GOLD-A", REPO_ROOT)
    assert case.expected_domain == "corrosion"
    assert case.filename == "Corrosion 1.pdf"
    assert case.pdf_path.exists()
    assert case.gold_path is not None and case.gold_path.exists()


def test_live_corrosion_holdout_is_blocked_before_provider_use():
    with pytest.raises(ValueError, match="holdout"):
        load_live_case(HOLDOUT_CASE_ID, REPO_ROOT)


def test_gold_a_expectations_preserve_printed_values_and_units_without_conversion():
    case = load_live_case("CORR-GOLD-A", REPO_ROOT)
    gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
    expected = expectations_from_gold(gold)
    assert len(expected) == 4
    assert {(item.metric, item.value, item.unit) for item in expected} == {
        ("solution_resistance", 75.21, "Ω·cm2"),
        ("charge_transfer_resistance", 14600.0, "Ω·cm2"),
        ("solution_resistance", 22.19, "Ω·cm2"),
        ("charge_transfer_resistance", 35600.0, "Ω·cm2"),
    }
    # Gold prose uses the long human-readable name, while canonical Corrosion V1
    # experiment records use the controlled taxonomy token "eis".
    assert all(item.experiment_type == "eis" for item in expected)
    assert all(item.material_contains == "14Cr12Ni3Mo2VN" for item in expected)


def test_live_pipeline_is_pinned_and_has_no_search_or_ocr():
    # The pipeline constructor does not create or write this directory. Using a stable
    # non-temporary path keeps this configuration-only test independent of Windows
    # pytest temp-directory cleanup/locking behaviour.
    output_dir = Path("output") / "pytest-corrosion-live-config"
    pipeline = build_live_pipeline(output_dir)
    assert pipeline.provider_mode == "benchmark"
    assert pipeline.search_assisted is False
    assert pipeline.find_supplementary is False
    assert pipeline.enable_ocr is False
    assert pipeline.visual_sidecar_store.output_directory == output_dir


def test_negative_control_is_not_expected_to_route_to_corrosion():
    case = load_live_case("CORR-NEGATIVE-H", REPO_ROOT)
    assert case.expected_domain == "not_corrosion"


def test_offline_diagnostics_exposes_canonical_and_quarantined_metrics():
    # Keep this fixture under the repository's git-ignored output/ tree instead of
    # pytest's Windows temporary directory. Some Windows/AV combinations retain a
    # handle to pytest temp folders long enough for pytest cleanup to raise WinError 5.
    workspace = REPO_ROOT / "output" / "pytest-corrosion-live-diagnostics-workspace"
    case_dir = workspace / "output" / "corrosion_v1" / "live" / "CORR-GOLD-A"
    case_dir.mkdir(parents=True, exist_ok=True)
    archive = {
        "metadata": {"archive_id": "arc-test", "domain": "corrosion"},
        "sources": [{"source_id": "src-test", "title": "Paper"}],
        "materials": [{"material_id": "mat-test", "name": "Alloy"}],
        "experiments": [{
            "experiment_id": "exp-test",
            "experiment_type": "eis",
            "material_ids": ["mat-test"],
            "outputs": [{
                "property": "solution_resistance",
                "raw_value": "75.21 Ω·cm2",
                "value": 75.21,
                "unit": "Ω·cm2",
                "evidence": [{"verbatim_match": True}],
            }],
        }],
        "domain_payloads": [{
            "domain": "corrosion",
            "schema_version": "1",
            "values": {
                "admissibility_audit": {
                    "quarantine": [{
                        "path": "experiments.exp-test.metrics.1",
                        "reason": "no_verified_value_specific_evidence",
                        "ownership": "focal_work",
                        "object": {
                            "property": "charge_transfer_resistance",
                            "quantity": {"raw_value": "1.46×10^4 Ω·cm2", "value": 14600.0, "unit": "Ω·cm2"},
                            "ownership": "focal_work",
                            "evidence": [{"verbatim_match": False}],
                        },
                    }],
                }
            },
        }],
    }
    report = {
        "case_id": "CORR-GOLD-A",
        "score": {"matched_required": 0},
        "extraction_diagnostics": {"primary_calls": 1, "schema_repair_calls": 0},
        "provider_audit": {"mode": "benchmark"},
    }
    (case_dir / "archive.json").write_text(json.dumps(archive), encoding="utf-8")
    (case_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

    diagnostic = diagnose_live_output("CORR-GOLD-A", workspace)
    assert diagnostic["canonical_metric_count"] == 1
    assert diagnostic["canonical_metrics"][0]["property"] == "solution_resistance"
    assert diagnostic["quarantine_reason_counts"] == {"no_verified_value_specific_evidence": 1}
    assert diagnostic["quarantined_metrics"][0]["property"] == "charge_transfer_resistance"
    assert diagnostic["quarantined_metrics"][0]["verified_evidence_count"] == 0
