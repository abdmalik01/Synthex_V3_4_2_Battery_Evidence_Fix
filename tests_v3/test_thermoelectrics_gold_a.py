from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from benchmark.thermoelectrics_v1.recover_gold_a import recover_gold_a, supplementary_local_status
from benchmark.thermoelectrics_v1.raw_scoring import score_raw_gold_a
from benchmark.thermoelectrics_v1.score_gold_a import score_gold_a
from synthex_platform.extraction.router import DomainRouter


CASE_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "thermoelectrics_v1"


def _gold() -> dict:
    return json.loads((CASE_DIR / "gold_a.json").read_text(encoding="utf-8"))


def test_te_gold_a_supplement_is_optional_but_any_local_copy_must_match(tmp_path):
    lock = json.loads((CASE_DIR / "source_lock.json").read_text(encoding="utf-8"))
    local = CASE_DIR / lock["supplementary_file"]
    assert supplementary_local_status(lock, tmp_path / "not-downloaded.pdf") == "not_available_locally"
    if local.exists():
        assert supplementary_local_status(lock, local) == "verified_local"
    wrong = tmp_path / "wrong.pdf"
    wrong.write_bytes(b"not the locked publisher supplement")
    with pytest.raises(ValueError, match="checksum changed"):
        supplementary_local_status(lock, wrong)


def test_te_gold_a_locked_sources_recover_all_exact_series_offline():
    archive, recovered = recover_gold_a()
    report = score_gold_a(archive, _gold())
    assert report["passed"] is True
    assert report["outputs"] == report["analytics_rows"] == 102
    assert all(checks["digest_correct"] for checks in report["series"].values())
    assert report["scientific_safety"] == {
        "signed_seebeck_preserved": True,
        "measured_vs_derived_preserved": True,
        "thermal_property_identity_preserved": True,
        "single_material_association": True,
        "analytics_preserve_temperature_and_material": True,
        "quarantine_count": 0,
    }
    assert {name: len(points) for name, points in recovered.items()} == {
        "electrical_conductivity": 22,
        "seebeck_coefficient": 22,
        "power_factor": 22,
        "zt": 12,
        "lattice_thermal_conductivity": 12,
        "total_thermal_conductivity": 12,
    }


def test_te_gold_a_preserves_composition_processing_and_one_material_series():
    archive, _ = recover_gold_a()
    assert len(archive.materials) == 1
    material = archive.materials[0]
    assert material.formula == "Na0.03Sn0.965Se"
    assert material.composition == {"Na": 0.03, "Sn": 0.965, "Se": 1.0}
    assert len(archive.processes) == 1
    parameters = {item.property: (item.value, item.unit) for item in archive.processes[0].parameters}
    assert parameters["reaction_temperature"] == (1223.0, "K")
    assert parameters["annealing_time"] == (48.0, "h")
    assert parameters["sintering_pressure"] == (50.0, "MPa")
    assert parameters["relative_density"] == (95.6, "%")
    assert all(experiment.material_ids == [material.material_id] for experiment in archive.experiments)


def test_te_gold_a_seebeck_sign_and_thermal_property_identity_are_explicit():
    archive, _ = recover_gold_a()
    by_property = {
        output.property: []
        for experiment in archive.experiments for output in experiment.outputs
    }
    for experiment in archive.experiments:
        for output in experiment.outputs:
            by_property[output.property].append(output)
    assert all(
        item.value > 0 and item.conditions["seebeck_sign"] == "positive"
        and item.conditions["absolute_value"] is False
        for item in by_property["seebeck_coefficient"]
    )
    assert by_property["lattice_thermal_conductivity"][-1].value == 0.07805
    assert by_property["total_thermal_conductivity"][-1].value == 0.21632
    assert all(item.conditions["derivation_basis"] for item in by_property["zt"])


def test_official_te_gold_a_article_routes_to_thermoelectrics():
    with pymupdf.open(CASE_DIR / "corpus_pdfs" / "TE-GOLD-A_article.pdf") as document:
        text = "\n".join(page.get_text() for page in document)
    route = DomainRouter().route_text(text)
    assert route.domain == "thermoelectrics"
    assert "thermoelectric_performance" in route.paper_types
    assert "electrical_transport" in route.paper_types
    assert "thermal_transport" in route.paper_types


def test_raw_scoring_handles_schema_invalid_flat_measurements_without_admission():
    _, expected = recover_gold_a()
    payload = {
        "materials": [{"local_id": "m1", "composition": "Na0.03Sn0.965Se"}],
        "measurements": [{
            "canonical_property": "seebeck_coefficient", "material_ref": "m1",
            "raw_value": "268.60032 uV/K", "temperature": "783.21932 K",
            "locator": "workbook=Fig5;sheet=Figure 5b;source_row=23",
        }],
    }
    score = score_raw_gold_a(payload, expected, _gold())
    assert score["raw_output_count"] == score["flat_measurement_count"] == 1
    assert score["series"]["seebeck_coefficient"]["exact_points"] == 1
    assert score["sample_association_present"] is True
    assert score["temperature_association_present"] is True
    assert score["evidence_locations_present"] is True
    assert score["scientific_type_explicit"] is False
    assert score["canonical_admission_not_implied"] is True
