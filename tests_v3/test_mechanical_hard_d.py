from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_hard_d import recover_hard_d
from benchmark.mechanical_v1.score_hard_d import score_hard_d
from benchmark.mechanical_v1.score_hard_d_raw import score_raw_hard_payload
from synthex_platform.extraction.mechanical_contract import mechanical_admission_decision
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


@pytest.fixture(scope="module")
def hard_case():
    source, gold, lock = load_locked_case("MECH-HARD-D")
    archive, recovered = recover_hard_d()
    return source, gold, lock, archive, recovered


def test_hardness_primary_source_and_reviewed_gold_are_frozen(hard_case):
    source, gold, lock, _, _ = hard_case
    assert sha256(source.read_bytes()).hexdigest() == lock["source_sha256"]
    assert gold["assertion_count"] == lock["assertions"] == 18
    assert gold["gold_basis"]["table"] == "Table 4"


def test_hardness_recovery_scores_every_cell_with_cell_provenance(hard_case):
    _, gold, _, archive, recovered = hard_case
    score = score_hard_d(archive, gold)
    assert (score["passed"], score["total"]) == (18, 18)
    assert score["association_accuracy"] == score["source_tracking"] == 1.0
    assert score["scale_safety"] is True
    assert len(archive.experiments) == len(recovered) == 18
    assert all("bbox=" in row["locator"] and row["table_id"].startswith("tbl-") for row in recovered)
    assert all(
        mechanical_admission_decision(output, modality="experimental").admitted
        for experiment in archive.experiments for output in experiment.outputs
    )


def test_hardness_sample_or_cooling_rate_swap_fails_gold(hard_case):
    _, gold, _, archive, _ = hard_case
    altered = archive.model_copy(deep=True)
    altered.experiments[0].outputs[0].conditions["cooling_rate"] = 30.0
    score = score_hard_d(altered, gold)
    assert score["value_accuracy"] == 1.0
    assert score["association_accuracy"] < 1.0
    assert score["passed"] < 18


def test_hardness_scale_and_unit_are_not_interchangeable(hard_case):
    _, _, _, archive, _ = hard_case
    output = archive.experiments[0].outputs[0].model_copy(deep=True)
    output.property = "rockwell_hardness"
    output.unit = "HV"
    decision = mechanical_admission_decision(output, modality="experimental")
    assert not decision.admitted
    assert decision.reason == "incompatible_unit"


def test_hardness_locked_source_routes_to_mechanical(hard_case):
    source, _, _, _, _ = hard_case
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    assert route.domain == "mechanical"
    assert "hardness_testing" in route.paper_types


def test_hardness_raw_scorer_requires_conditions_ownership_and_evidence(hard_case):
    _, gold, _, _, _ = hard_case
    materials = []
    experiments = []
    for index, expected in enumerate(gold["rows"]):
        material_id = f"material_{index}"
        materials.append({"local_id": material_id, "name": expected["sample"], "ownership": "focal_work"})
        experiments.append({
            "local_id": f"experiment_{index}", "material_id": material_id, "ownership": "focal_work",
            "measurements": [{
                "property": "vickers_hardness", "raw_value": expected["raw_value"],
                "value": expected["value"], "unit": "HV", "uncertainty": expected["uncertainty"],
                "conditions": [
                    {"name": "cooling_rate", "value": float(expected["cooling_rate_c_per_s"])},
                    {"name": "hardness_scale", "value": "Vickers"},
                    {"name": "test_load_kgf", "value": 0.5},
                    {"name": "number_of_indents", "value": 5},
                    {"name": "dwell_time", "value": "not_reported"},
                    {"name": "scientific_type", "value": "reported_measurement"},
                ],
                "source": {"table_id": "Table 4"},
            }],
        })
    score = score_raw_hard_payload({"materials": materials, "experiments": experiments}, gold)
    assert score["value_accuracy"] == score["association_accuracy"] == 1.0
    assert score["ownership_accuracy"] == 1.0
    assert score["source_tracking"] == 0.0
    assert score["passed"] == 0
