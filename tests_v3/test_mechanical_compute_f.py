from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_compute_f import recover_compute_f
from benchmark.mechanical_v1.score_compute_f import score_compute_f
from synthex_platform.extraction.mechanical_contract import mechanical_admission_decision
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


@pytest.fixture(scope="module")
def compute_case():
    source, gold, lock = load_locked_case("MECH-COMPUTE-F")
    archive, recovered = recover_compute_f()
    return source, gold, lock, archive, recovered


def test_compute_source_and_gold_are_frozen(compute_case):
    source, gold, lock, _, _ = compute_case
    assert sha256(source.read_bytes()).hexdigest() == lock["source_sha256"]
    assert gold["assertion_count"] == lock["assertions"] == 28
    assert gold["gold_basis"]["record_kind"] == "CalculationRecord"


def test_compute_recovery_scores_all_cells_as_calculations(compute_case):
    _, gold, _, archive, recovered = compute_case
    score = score_compute_f(archive, gold)
    assert (score["passed"], score["total"]) == (28, 28)
    assert score["value_accuracy"] == score["source_tracking"] == 1.0
    assert score["experiment_separation"] is True
    assert len(archive.experiments) == 0
    assert len(archive.calculations) == 4
    assert len(recovered) == score["calculation_outputs"] == 28
    assert all("row=" in item["locator"] and "bbox=" in item["locator"] for item in recovered)


def test_compute_properties_remain_distinct(compute_case):
    _, _, _, archive, _ = compute_case
    properties = {output.property for item in archive.calculations for output in item.outputs}
    assert properties == {
        "elastic_constant_c11", "elastic_constant_c12", "elastic_constant_c44",
        "bulk_modulus", "shear_modulus", "youngs_modulus", "poisson_ratio",
    }
    assert all(
        mechanical_admission_decision(output, modality="computational").admitted
        for item in archive.calculations for output in item.outputs
    )


def test_reported_measurement_cannot_enter_compute_calculation(compute_case):
    _, _, _, archive, _ = compute_case
    output = archive.calculations[0].outputs[0].model_copy(deep=True)
    output.conditions["scientific_type"] = "reported_measurement"
    decision = mechanical_admission_decision(output, modality="computational")
    assert not decision.admitted
    assert decision.reason == "non_model_result_in_calculation"


def test_compute_locked_source_routes_to_mechanical_computational(compute_case):
    source, _, _, _, _ = compute_case
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    assert route.domain == "mechanical"
    assert "computational_mechanics" in route.paper_types
