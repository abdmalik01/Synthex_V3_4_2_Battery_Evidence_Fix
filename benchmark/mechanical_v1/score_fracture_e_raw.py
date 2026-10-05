"""Semantic score for an immutable raw MECH-FRACTURE-E provider payload."""

from __future__ import annotations

import math
import re
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _conditions(measurement: dict) -> dict[str, Any]:
    value = measurement.get("conditions", {})
    if isinstance(value, dict):
        return value
    result = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                result[item["name"]] = item.get("value", item.get("raw_value"))
    return result


def _measurements(experiment: dict) -> list[dict]:
    value = experiment.get("outputs", experiment.get("measurements", []))
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _material_ref(experiment: dict) -> str | None:
    if experiment.get("material_id"):
        return experiment["material_id"]
    refs = experiment.get("material_refs", [])
    return refs[0] if isinstance(refs, list) and len(refs) == 1 else None


def _condition(conditions: dict, *names: str):
    for name in names:
        if name in conditions:
            return conditions[name]
    return None


def _condition_number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value", value.get("raw_value"))
    return _number(value)


def _sample(measurement: dict, experiment: dict, conditions: dict) -> str | None:
    value = _condition(conditions, "sample", "specimen", "specimen_id")
    if value is None:
        value = experiment.get("sample", experiment.get("specimen_id"))
    if value is None and isinstance(measurement.get("evidence"), str):
        match = re.search(r"FT\((?:O|160|200|250)\)\d+", measurement["evidence"])
        value = match.group() if match else None
    return str(value) if value is not None else None


def _treatment_from_material(material: dict) -> str | None:
    name = str(material.get("name", ""))
    if "original treatment" in name:
        return "original"
    for temperature in (160, 200, 250):
        if str(temperature) in name:
            return f"tempered_{temperature}_c"
    return None


def _unit_is_fracture_toughness(unit: Any) -> bool:
    value = re.sub(r"\s+", "", str(unit or "")).casefold().replace("·", "*")
    return value in {"mpa*sqrt(m)", "mpa√m", "mpam^0.5", "mpam1/2", "mpa*m^0.5"}


def _evidence_complete(measurement: dict) -> bool:
    evidence = measurement.get("evidence")
    if evidence is None and isinstance(measurement.get("source"), dict):
        evidence = [measurement["source"]]
    if isinstance(evidence, dict):
        evidence = [evidence]
    return isinstance(evidence, list) and any(
        isinstance(item, dict) and item.get("page") and item.get("table_id")
        and item.get("locator") and item.get("text_snippet")
        and item.get("verbatim_match") is True for item in evidence
    )


def score_raw_fracture_payload(payload: dict, gold: dict) -> dict:
    experiments = [item for item in payload.get("experiments", []) if isinstance(item, dict)]
    materials = {
        item.get("local_id"): item for item in payload.get("materials", [])
        if isinstance(item, dict) and item.get("local_id")
    }
    experiments_by_id = {
        item.get("local_id"): item for item in experiments if item.get("local_id")
    }
    observations = []
    for experiment in experiments:
        material = materials.get(_material_ref(experiment), {})
        for measurement in _measurements(experiment):
            observations.append((experiment, material, measurement, _conditions(measurement)))
    for measurement in payload.get("measurements", []):
        if not isinstance(measurement, dict):
            continue
        experiment = experiments_by_id.get(measurement.get("experiment_id"), {})
        material = materials.get(measurement.get("material_id"), {})
        observations.append((experiment, material, measurement, _conditions(measurement)))
    assertions = []
    promotions = 0
    inferred_orientations = 0
    for expected in gold["rows"]:
        candidates = []
        for experiment, material, measurement, conditions in observations:
            if _sample(measurement, experiment, conditions) != expected["sample"]:
                continue
            if measurement.get("property") not in {"fracture_toughness", "K_IC", "K_JC", "K_JU"}:
                continue
            candidates.append((experiment, material, measurement, conditions))
        value_rows = [item for item in candidates if (
            item[2].get("raw_value") == expected["raw_value"]
            and _number(item[2].get("value", item[2].get("raw_value"))) == float(expected["value"])
            and _unit_is_fracture_toughness(item[2].get("unit"))
        )]
        association_rows = [item for item in value_rows if (
            _condition_number(_condition(item[3], "test_temperature_c", "test_temperature", "temperature"))
            == float(expected["test_temperature_c"])
            and (
                str(_condition(item[3], "processing_state", "treatment", "heat_treatment"))
                if _condition(item[3], "processing_state", "treatment", "heat_treatment") is not None
                else _treatment_from_material(item[1])
            ) == expected["treatment"]
        )]
        metric_rows = [item for item in association_rows if (
            str(_condition(item[3], "reported_metric", "reported_term", "metric")) == expected["reported_metric"]
            and str(_condition(item[3], "validity", "validity_status")) == expected["validity"]
        )]
        scientific_rows = [item for item in metric_rows if (
            _condition(item[3], "scientific_type") == (
                "reported_measurement" if expected["reported_metric"] == "K_IC"
                else "reported_derived_metric"
            )
        )]
        ownership_rows = [item for item in scientific_rows if (
            item[0].get("ownership") == "focal_work" and item[1].get("ownership") == "focal_work"
        )]
        evidence_rows = [item for item in ownership_rows if _evidence_complete(item[2])]
        assertions.append({
            "sample": expected["sample"], "value_unit_correct": bool(value_rows),
            "association_correct": bool(association_rows), "metric_validity_correct": bool(metric_rows),
            "scientific_type_correct": bool(scientific_rows), "ownership_correct": bool(ownership_rows),
            "source_tracked": bool(evidence_rows), "passed": bool(evidence_rows),
        })
        for _, _, measurement, conditions in candidates:
            actual_metric = str(_condition(conditions, "reported_metric", "reported_term", "metric"))
            if expected["reported_metric"] in {"K_JC", "K_JU"} and actual_metric == "K_IC":
                promotions += 1
            if _condition(conditions, "orientation") not in {None, "", "not_reported"}:
                inferred_orientations += 1
    total = len(assertions)
    return {
        "case_id": gold["case_id"], "schema_valid": False,
        "passed": sum(item["passed"] for item in assertions), "total": total,
        "overall": sum(item["passed"] for item in assertions) / total,
        "value_unit_accuracy": sum(item["value_unit_correct"] for item in assertions) / total,
        "association_accuracy": sum(item["association_correct"] for item in assertions) / total,
        "metric_validity_accuracy": sum(item["metric_validity_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "ownership_accuracy": sum(item["ownership_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "conditional_or_invalid_promoted_to_kic": promotions,
        "inferred_orientation_count": inferred_orientations,
        "assertions": assertions,
    }
