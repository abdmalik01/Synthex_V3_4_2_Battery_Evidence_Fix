from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_fracture_e import recover_fracture_e
from benchmark.mechanical_v1.score_fracture_e import score_fracture_e
from synthex_platform.extraction.mechanical_contract import mechanical_admission_decision
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


@pytest.fixture(scope="module")
def fracture_case():
    source, gold, lock = load_locked_case("MECH-FRACTURE-E")
    archive, recovered = recover_fracture_e()
    return source, gold, lock, archive, recovered


def test_fracture_primary_source_and_reviewed_gold_are_frozen(fracture_case):
    source, gold, lock, _, _ = fracture_case
    assert sha256(source.read_bytes()).hexdigest() == lock["source_sha256"]
    assert gold["assertion_count"] == lock["assertions"] == 27
    assert gold["gold_basis"]["table"] == "Table 6"


def test_fracture_recovery_preserves_all_metric_validity_classes(fracture_case):
    _, gold, _, archive, recovered = fracture_case
    score = score_fracture_e(archive, gold)
    assert (score["passed"], score["total"]) == (27, 27)
    assert score["association_accuracy"] == score["source_tracking"] == 1.0
    assert score["metric_safety"] is True
    assert score["conditional_count"] == 1
    assert score["invalid_count"] == 3
    assert len(archive.experiments) == len(recovered) == 27
    assert len(archive.materials) == len(archive.processes) == 4
    assert all("bbox=" in row["locator"] and row["table_id"].startswith("tbl-") for row in recovered)
    assert all(
        mechanical_admission_decision(output, modality="experimental").admitted
        for experiment in archive.experiments for output in experiment.outputs
    )


def test_fracture_invalid_kju_cannot_be_promoted_to_kic(fracture_case):
    _, gold, _, archive, _ = fracture_case
    altered = archive.model_copy(deep=True)
    invalid = next(
        output for experiment in altered.experiments for output in experiment.outputs
        if output.conditions.get("reported_metric") == "K_JU"
    )
    invalid.conditions["reported_metric"] = "K_IC"
    invalid.conditions["reported_term"] = "K_IC"
    invalid.conditions["validity"] = "valid_linear_elastic_plane_strain"
    invalid.conditions["scientific_type"] = "reported_measurement"
    score = score_fracture_e(altered, gold)
    assert score["metric_validity_accuracy"] < 1.0
    assert score["passed"] < 27


def test_fracture_toughness_unit_is_not_ordinary_stress(fracture_case):
    _, _, _, archive, _ = fracture_case
    output = archive.experiments[0].outputs[0].model_copy(deep=True)
    output.unit = "MPa"
    decision = mechanical_admission_decision(output, modality="experimental")
    assert not decision.admitted
    assert decision.reason == "incompatible_unit"


def test_explicit_na_is_rejected_even_with_a_numeric_normalized_value(fracture_case):
    _, _, _, archive, _ = fracture_case
    output = archive.experiments[0].outputs[0].model_copy(deep=True)
    output.raw_value = "N/A"
    output.value = 23.3
    output.normalized_value = 23.3
    output.evidence[0].text_snippet = "N/A"
    decision = mechanical_admission_decision(output, modality="experimental")
    assert not decision.admitted
    assert decision.reason == "explicit_missing_source_value"


def test_fracture_locked_source_routes_to_mechanical(fracture_case):
    source, _, _, _, _ = fracture_case
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    assert route.domain == "mechanical"
    assert "fracture_toughness" in route.paper_types
