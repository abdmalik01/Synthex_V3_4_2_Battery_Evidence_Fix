from pathlib import Path

import pytest

from synthex_platform.benchmarks.corrosion_live import (
    HOLDOUT_CASE_ID,
    build_live_pipeline,
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
    import json

    gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
    expected = expectations_from_gold(gold)
    assert len(expected) == 4
    assert {(item.metric, item.value, item.unit) for item in expected} == {
        ("solution_resistance", 75.21, "Ω·cm2"),
        ("charge_transfer_resistance", 14600.0, "Ω·cm2"),
        ("solution_resistance", 22.19, "Ω·cm2"),
        ("charge_transfer_resistance", 35600.0, "Ω·cm2"),
    }
    assert all(item.experiment_type == "electrochemical impedance spectroscopy" for item in expected)
    assert all(item.material_contains == "14Cr12Ni3Mo2VN" for item in expected)


def test_live_pipeline_is_pinned_and_has_no_search_or_ocr(tmp_path):
    pipeline = build_live_pipeline(tmp_path)
    assert pipeline.provider_mode == "benchmark"
    assert pipeline.search_assisted is False
    assert pipeline.find_supplementary is False
    assert pipeline.enable_ocr is False
    assert pipeline.visual_sidecar_store.output_directory == tmp_path


def test_negative_control_is_not_expected_to_route_to_corrosion():
    case = load_live_case("CORR-NEGATIVE-H", REPO_ROOT)
    assert case.expected_domain == "not_corrosion"
