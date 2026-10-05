"""Frozen-gold scorers for the three Thermoelectrics expansion cases."""

from __future__ import annotations

import hashlib
import json

from synthex_platform.visual.analytics.projection import project_archives


def _digest(points: list[list[float]]) -> str:
    return hashlib.sha256(json.dumps(points, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _outputs(archive):
    return [output for experiment in archive.experiments for output in experiment.outputs]


def _quarantine(archive) -> list:
    return archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def score_series_b(archive, gold: dict) -> dict:
    material_by_formula = {material.formula: material for material in archive.materials}
    sample_by_material_id = {material.material_id: sample_id for sample_id, spec in gold["samples"].items() for material in archive.materials if material.formula == spec["formula"]}
    actual: dict[str, list] = {}
    experiment_integrity = True
    for experiment in archive.experiments:
        if len(experiment.material_ids) != 1 or experiment.material_ids[0] not in sample_by_material_id:
            experiment_integrity = False
            continue
        sample_id = sample_by_material_id[experiment.material_ids[0]]
        for output in experiment.outputs:
            actual.setdefault(f"{sample_id}/{output.property}", []).append(output)
            experiment_integrity &= output.conditions.get("sample_identity") == sample_id
    checks = {}
    for key, expected in gold["series"].items():
        items = actual.get(key, [])
        points = [[float(item.conditions["temperature"]), float(item.value)] for item in items]
        checks[key] = {
            "count": len(points) == expected["count"], "digest": _digest(points) == expected["sha256"],
            "sentinels": all(point in points for point in expected["sentinels"]),
            "unit": all(item.unit == expected["unit"] for item in items),
            "orientation": all(item.conditions.get("measurement_orientation") == "parallel to SPS direction" for item in items),
            "evidence": all(item.evidence and item.evidence[0].original_source_type == "official_source_data_workbook" and item.evidence[0].locator for item in items),
        }
    analytics = project_archives([archive])
    material_correct = all(spec["formula"] in material_by_formula and material_by_formula[spec["formula"]].composition == spec["composition"] for spec in gold["samples"].values())
    seebeck = [item for item in _outputs(archive) if item.property == "seebeck_coefficient"]
    passed = material_correct and experiment_integrity and all(all(entry.values()) for entry in checks.values()) and len(analytics) == gold["expected_outputs"] and not _quarantine(archive)
    return {
        "case_id": gold["case_id"], "passed": passed, "outputs": len(_outputs(archive)), "analytics_rows": len(analytics), "quarantine": len(_quarantine(archive)),
        "series": checks, "scientific_safety": {
            "three_distinct_samples": len(archive.materials) == 3 and len(sample_by_material_id) == 3,
            "sample_association_preserved": experiment_integrity,
            "per_sample_temperature_grids_preserved": len({tuple(point[0] for point in [[float(i.conditions['temperature']), float(i.value)] for i in actual[key]]) for key in actual if key.endswith('/electrical_conductivity')}) == 3,
            "signed_seebeck_preserved": bool(seebeck) and all(item.value > 0 and item.conditions.get("seebeck_sign") == "positive" and item.conditions.get("absolute_value") is False for item in seebeck),
            "reported_pf_not_zt": all(item.property == "power_factor" and item.conditions.get("scientific_type") == "reported_derived_metric" for item in _outputs(archive) if item.property == "power_factor"),
            "analytics_identity_complete": len(analytics) == gold["expected_outputs"] and all(row.material_id and row.conditions.get("temperature") is not None and row.conditions.get("measurement_orientation") for row in analytics),
        },
    }


def score_derived_c(archive, gold: dict, validation: dict) -> dict:
    by_property: dict[str, list] = {}
    for item in _outputs(archive):
        by_property.setdefault(item.property, []).append(item)
    checks = {}
    for name, expected in gold["series"].items():
        items = by_property.get(name, [])
        points = [[float(item.conditions["temperature"]), float(item.value)] for item in items]
        checks[name] = {
            "count": len(points) == expected["count"], "digest": _digest(points) == expected["sha256"],
            "unit": all(item.unit == expected["unit"] for item in items),
            "scientific_type": all(item.conditions.get("scientific_type") == expected["scientific_type"] for item in items),
            "derivation_basis": all(bool(item.conditions.get("derivation_basis")) for item in items) if expected["scientific_type"] == "reported_derived_metric" else all(not item.conditions.get("derivation_basis") for item in items),
        }
    analytics = project_archives([archive])
    no_synthex_outputs = all(item.conditions.get("scientific_type") != "synthex_derived_metric" for item in _outputs(archive))
    validation_only = validation["canonical_measurements_created"] == 0 and validation["max_relative_error"] <= gold["formula_validation"]["max_relative_error"]
    passed = all(all(entry.values()) for entry in checks.values()) and no_synthex_outputs and validation_only and len(analytics) == gold["expected_outputs"] and not _quarantine(archive)
    return {"case_id": gold["case_id"], "passed": passed, "outputs": len(_outputs(archive)), "analytics_rows": len(analytics), "quarantine": len(_quarantine(archive)), "series": checks, "formula_validation": validation, "no_silent_derivation": no_synthex_outputs and validation_only}


def score_aniso_d(archive, gold: dict) -> dict:
    outputs = _outputs(archive)
    actual = {(item.conditions.get("measurement_orientation"), item.property): item for item in outputs}
    checks = []
    for expected in gold["measurements"]:
        item = actual.get((expected["orientation"], expected["property"]))
        checks.append(bool(item and item.value == expected["value"] and item.unit == expected["unit"] and item.conditions.get("temperature") == expected["temperature"] and item.conditions.get("scientific_type") == expected["scientific_type"] and item.conditions.get("derivation_basis") and item.evidence and item.raw_value in (item.evidence[0].text_snippet or "")))
    analytics = project_archives([archive])
    orientations = {item.conditions.get("measurement_orientation") for item in outputs}
    passed = all(checks) and orientations == {"c-axis", "ab-plane"} and len(outputs) == len(analytics) == gold["expected_outputs"] and not _quarantine(archive)
    return {"case_id": gold["case_id"], "passed": passed, "outputs": len(outputs), "analytics_rows": len(analytics), "quarantine": len(_quarantine(archive)), "orientation_specific_values": dict(sorted((orientation, actual[(orientation, "lattice_thermal_conductivity")].value) for orientation in orientations)), "orientation_not_averaged": len(orientations) == 2 and len(outputs) == 2, "plot_only_values_excluded": archive.domain_payloads[0].values.get("plot_only_values_excluded") is True}
