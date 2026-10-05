from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_creep_b import recover_creep_b
from benchmark.mechanical_v1.score_creep_b import score_creep_b
from benchmark.mechanical_v1.score_creep_b_raw import score_raw_creep_payload
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


@pytest.fixture(scope="module")
def creep_case():
    source, gold, lock = load_locked_case("MECH-CREEP-B")
    archive, recovered, omitted = recover_creep_b()
    return source, gold, lock, archive, recovered, omitted


def test_creep_source_and_reviewed_gold_are_frozen(creep_case):
    source, gold, lock, _, _, _ = creep_case
    assert sha256(source.read_bytes()).hexdigest() == lock["source_sha256"]
    assert gold["assertion_count"] == lock["assertions"] == 24
    assert gold["gold_basis"]["table"] == "Table 2"


def test_creep_recovery_scores_all_cells_and_excludes_unusable_rows(creep_case):
    _, gold, _, archive, recovered, omitted = creep_case
    score = score_creep_b(archive, gold)
    assert (score["passed"], score["total"]) == (24, 24)
    assert score["association_accuracy"] == score["source_tracking"] == 1.0
    assert score["excluded_row_correctness"] == 1.0
    assert len(omitted) == 3 and len(archive.experiments) == 13
    assert all("bbox=" in cell["locator"] and cell["table_id"].startswith("tbl-") for cell in recovered)
    assert archive.calculations == []
    assert not any(output.property in {"minimum_creep_rate", "creep_rate", "yield_strength"}
                   for experiment in archive.experiments for output in experiment.outputs)


def test_creep_swapped_stress_association_fails_gold(creep_case):
    _, gold, _, archive, _, _ = creep_case
    swapped = archive.model_copy(deep=True)
    first = swapped.experiments[0]
    for output in first.outputs:
        output.conditions["applied_stress"] = 120
    score = score_creep_b(swapped, gold)
    assert score["value_accuracy"] == 1.0
    assert score["association_accuracy"] < 1.0
    assert score["passed"] < 24


def test_creep_source_routes_to_mechanical(creep_case):
    source, _, _, _, _, _ = creep_case
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    assert route.domain == "mechanical"
    assert "creep_stress_rupture" in route.paper_types


def test_creep_raw_payload_scores_semantics_but_not_unverified_evidence(creep_case):
    _, gold, _, _, _, _ = creep_case
    property_map = (
        ("rupture_time_h", "rupture_time", "h"),
        ("rupture_strain_percent", "rupture_strain", "%"),
        ("time_to_1_percent_h", "time_to_specific_strain", "h"),
    )
    experiments = []
    for index, row in enumerate(gold["rows"], start=1):
        measurements = []
        for gold_key, property_name, unit in property_map:
            raw_value = row[gold_key]
            measurements.append({
                "property": property_name,
                "raw_value": raw_value,
                "value": float(raw_value),
                "unit": unit,
                "conditions": [
                    {"name": "temperature", "value": row["test_temperature_c"]},
                    {"name": "applied_stress", "value": row["applied_stress_mpa"]},
                    {"name": "scientific_type", "value": "reported_measurement"},
                ],
                "source": {"table_id": "Table 2"},
            })
        experiments.append({
            "local_id": f"experiment_{index}",
            "material_id": "material_1",
            "ownership": "focal_work",
            "measurements": measurements,
        })
    payload = {
        "materials": [{
            "local_id": "material_1",
            "name": "diffusion-welded Alloy 617",
            "ownership": "focal_work",
            "processing_history": ["process_1", "process_2"],
        }],
        "experiments": experiments,
    }
    score = score_raw_creep_payload(payload, gold)
    assert score["value_accuracy"] == score["test_condition_accuracy"] == 1.0
    assert score["sample_accuracy"] == score["processing_accuracy"] == 1.0
    assert score["source_tracking"] == 0.0
    assert (score["passed"], score["total"]) == (0, 24)
    assert score["invalid_source_row_rejection"] == 1.0
