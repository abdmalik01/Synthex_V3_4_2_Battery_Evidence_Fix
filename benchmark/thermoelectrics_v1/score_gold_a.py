"""Frozen-gold scorer for TE-GOLD-A."""

from __future__ import annotations

import hashlib
import json

from synthex_platform.visual.analytics.projection import project_archives


def _digest(points: list[list[float]]) -> str:
    payload = json.dumps(points, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def score_gold_a(archive, gold: dict) -> dict:
    material = archive.materials[0] if len(archive.materials) == 1 else None
    process = archive.processes[0] if len(archive.processes) == 1 else None
    outputs = [output for experiment in archive.experiments for output in experiment.outputs]
    by_property = {}
    for output in outputs:
        by_property.setdefault(output.property, []).append(output)
    series_assertions = {}
    for property_name, expected in gold["series"].items():
        measurements = by_property.get(property_name, [])
        points = [[float(item.conditions["temperature"]), float(item.value)] for item in measurements]
        sentinels = expected["sentinels"]
        series_assertions[property_name] = {
            "count_correct": len(points) == expected["count"],
            "digest_correct": _digest(points) == expected["sha256"],
            "sentinels_present": all(sentinel in points for sentinel in sentinels),
            "unit_correct": all(item.unit == expected["unit"] for item in measurements),
            "context_complete": all(
                item.conditions.get("temperature_unit") == "K"
                and item.conditions.get("measurement_orientation") == "parallel to SPS direction"
                and item.conditions.get("carrier_type") == "p-type"
                for item in measurements
            ),
            "source_tracked": all(
                item.evidence
                and item.evidence[0].verbatim_match is True
                and item.evidence[0].original_source_type == "official_source_data_workbook"
                and item.evidence[0].table_id
                and item.evidence[0].locator
                and item.raw_value in (item.evidence[0].text_snippet or "")
                for item in measurements
            ),
        }
    process_parameters = {item.property: item for item in process.parameters} if process else {}
    process_correct = bool(process and all(
        name in process_parameters
        and process_parameters[name].value == expected[0]
        and process_parameters[name].unit == expected[1]
        for name, expected in gold["process"].items()
    ))
    analytics = project_archives([archive])
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    measured_properties = {"electrical_conductivity", "seebeck_coefficient"}
    derived_properties = {
        "power_factor", "zt", "lattice_thermal_conductivity", "total_thermal_conductivity"
    }
    return {
        "case_id": gold["case_id"],
        "passed": all(all(checks.values()) for checks in series_assertions.values())
        and process_correct and material is not None and len(analytics) == gold["expected_outputs"],
        "series": series_assertions,
        "material_correct": bool(
            material and material.formula == gold["material"]["formula"]
            and material.composition == gold["material"]["composition"]
            and "p-type" in material.tags
        ),
        "process_correct": process_correct,
        "scientific_safety": {
            "signed_seebeck_preserved": all(
                item.value > 0 and item.conditions.get("seebeck_sign") == "positive"
                and item.conditions.get("absolute_value") is False
                for item in by_property.get("seebeck_coefficient", [])
            ) and bool(by_property.get("seebeck_coefficient")),
            "measured_vs_derived_preserved": all(
                item.conditions.get("scientific_type") == "reported_measurement"
                for name in measured_properties for item in by_property.get(name, [])
            ) and all(
                item.conditions.get("scientific_type") == "reported_derived_metric"
                and item.conditions.get("derivation_basis")
                for name in derived_properties for item in by_property.get(name, [])
            ) and all(by_property.get(name) for name in measured_properties | derived_properties),
            "thermal_property_identity_preserved": {
                name for name in by_property if "thermal_conductivity" in name
            } == {"lattice_thermal_conductivity", "total_thermal_conductivity"},
            "single_material_association": bool(material) and all(
                len(experiment.material_ids) == 1 and experiment.material_ids[0] == material.material_id
                for experiment in archive.experiments
            ),
            "analytics_preserve_temperature_and_material": bool(material) and len(analytics) == gold["expected_outputs"] and all(
                row.material_id == material.material_id
                and isinstance(row.conditions.get("temperature"), float)
                and row.conditions.get("temperature_unit") == "K"
                for row in analytics
            ),
            "quarantine_count": len(quarantine),
        },
        "outputs": len(outputs),
        "analytics_rows": len(analytics),
    }
