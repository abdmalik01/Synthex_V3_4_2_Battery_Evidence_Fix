from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.thermoelectrics_v1.recover_expansion import recover_aniso_d, recover_derived_c, recover_series_b
from benchmark.thermoelectrics_v1.recover_gold_a import recover_gold_a
from benchmark.thermoelectrics_v1.score_expansion import score_aniso_d, score_derived_c, score_series_b
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.thermoelectrics_contract import TE_PROPERTIES
from synthex_platform.visual.analytics.projection import project_archives


CASE_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "thermoelectrics_v1"


def _gold(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _outputs(archive):
    return [item for experiment in archive.experiments for item in experiment.outputs]


def test_te_series_b_preserves_all_three_samples_and_exact_independent_grids():
    archive, recovered = recover_series_b()
    report = score_series_b(archive, _gold("gold_series_b.json"))
    assert report["passed"] is True
    assert report["outputs"] == report["analytics_rows"] == 198
    assert report["quarantine"] == 0
    assert all(report["scientific_safety"].values())
    assert len(recovered) == 9
    assert recovered["x001/electrical_conductivity"][0][0] != recovered["x002/electrical_conductivity"][0][0]
    assert recovered["x002/electrical_conductivity"][0][0] != recovered["x003/electrical_conductivity"][0][0]


def test_te_derived_c_preserves_source_reported_identity_and_validation_is_noncanonical():
    archive, _, validation = recover_derived_c()
    report = score_derived_c(archive, _gold("gold_derived_c.json"), validation)
    assert report["passed"] is True
    assert report["outputs"] == report["analytics_rows"] == 90
    assert report["quarantine"] == 0
    assert report["no_silent_derivation"] is True
    assert validation["points"] == 22
    assert validation["max_relative_error"] <= 2e-6
    assert validation["canonical_measurements_created"] == 0
    assert {item.conditions["scientific_type"] for item in _outputs(archive)} == {"reported_measurement", "reported_derived_metric"}


def test_te_aniso_d_preserves_exact_orientation_identity_without_digitizing_plots():
    archive, _ = recover_aniso_d()
    report = score_aniso_d(archive, _gold("gold_aniso_d.json"))
    assert report == {
        "case_id": "TE-ANISO-D", "passed": True, "outputs": 2, "analytics_rows": 2,
        "quarantine": 0, "orientation_specific_values": {"ab-plane": 2.3, "c-axis": 1.6},
        "orientation_not_averaged": True, "plot_only_values_excluded": True,
    }
    assert len(archive.materials) == 1
    assert all(experiment.material_ids == [archive.materials[0].material_id] for experiment in archive.experiments)


def test_interim_te_audit_is_30_of_30_with_no_cross_record_or_analytics_contamination():
    gold_a, _ = recover_gold_a()
    series_b, _ = recover_series_b()
    derived_c, _, _ = recover_derived_c()
    aniso_d, _ = recover_aniso_d()
    archives = [gold_a, series_b, derived_c, aniso_d]
    outputs = [item for archive in archives for item in _outputs(archive)]
    properties = {item.property for item in outputs}
    analytics = project_archives(archives)
    archive_material_ids = {material.material_id for archive in archives for material in archive.materials}
    audit = {
        1: "voltage" not in properties,
        2: all(item.conditions.get("seebeck_sign") == ("positive" if item.value > 0 else "negative" if item.value < 0 else "zero") for item in outputs if item.property == "seebeck_coefficient"),
        3: "electrical_conductivity" in properties and "total_thermal_conductivity" in properties,
        4: TE_PROPERTIES["electrical_resistivity"] != TE_PROPERTIES["electrical_conductivity"],
        5: TE_PROPERTIES["total_thermal_conductivity"] != TE_PROPERTIES["lattice_thermal_conductivity"],
        6: "electronic_thermal_conductivity" in TE_PROPERTIES and TE_PROPERTIES["total_thermal_conductivity"] != TE_PROPERTIES["electronic_thermal_conductivity"],
        7: {"lattice_thermal_conductivity", "electronic_thermal_conductivity"}.issubset(TE_PROPERTIES),
        8: "power_factor" in properties and "zt" in properties and TE_PROPERTIES["power_factor"].unit_family != TE_PROPERTIES["zt"].unit_family,
        9: "efficiency" not in properties,
        10: all(item.unit == "dimensionless" for item in outputs if item.property == "zt"),
        11: "z" not in properties,
        12: TE_PROPERTIES["carrier_concentration"].unit_family != "dimensionless",
        13: TE_PROPERTIES["carrier_mobility"].unit_family != TE_PROPERTIES["electrical_conductivity"].unit_family,
        14: all(item.conditions.get("temperature_unit") == "K" for item in outputs),
        15: all(len(experiment.material_ids) == 1 for archive in archives for experiment in archive.experiments),
        16: all(material.composition for archive in archives for material in archive.materials),
        17: all(material.dopants for archive in archives for material in archive.materials),
        18: bool(gold_a.processes and series_b.processes),
        19: all(isinstance(item.conditions.get("temperature"), float) for item in outputs),
        20: all(item.conditions.get("measurement_orientation") for item in outputs),
        21: {item.conditions.get("measurement_orientation") for item in _outputs(aniso_d)} == {"ab-plane", "c-axis"},
        22: series_b.domain_payloads[0].values.get("grid_policy") == "per-sample exact temperatures; no interpolation",
        23: {item.conditions.get("scientific_type") for item in _outputs(derived_c)} == {"reported_measurement", "reported_derived_metric"},
        24: all(item.conditions.get("scientific_type") != "synthex_derived_metric" for item in outputs),
        25: all(not archive.calculations for archive in archives),
        26: all(item.evidence and (item.evidence[0].page is not None or item.evidence[0].original_source_type == "official_source_data_workbook") for item in outputs),
        27: all((item.raw_value or "").casefold() not in {"n/a", "na", "not applicable"} for item in outputs),
        28: all(not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"] and archive.sources and archive.sources[0].doi for archive in archives),
        29: all(archive.domain_payloads[0].domain == "thermoelectrics" for archive in archives),
        30: len(analytics) == len(outputs) and all(row.material_id in archive_material_ids and row.conditions.get("temperature") is not None and row.conditions.get("measurement_orientation") for row in analytics),
    }
    assert len(audit) == 30
    assert audit == {index: True for index in range(1, 31)}


@pytest.mark.parametrize("text", [
    "Silicon transistor carrier mobility and electrical conductivity were measured versus temperature.",
    "A lithium-ion battery electrolyte showed higher ionic conductivity during cycling.",
    "The photovoltaic absorber carrier mobility and conductivity improved after annealing.",
    "A heat sink thermal-management composite showed high thermal conductivity.",
    "The thermocouple instrumentation voltage was calibrated over the temperature range.",
    "Generic polymer electrical conductivity was measured under applied voltage.",
])
def test_te_routing_does_not_steal_adjacent_transport_contexts(text):
    try:
        domain = DomainRouter().route_text(text).domain
    except ValueError:
        domain = None
    assert domain != "thermoelectrics"
