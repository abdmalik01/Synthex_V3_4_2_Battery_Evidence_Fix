"""Semantic score for an immutable raw MECH-HARD-D provider payload."""

from __future__ import annotations

import math
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


def score_raw_hard_payload(payload: dict, gold: dict) -> dict:
    experiments = [item for item in payload.get("experiments", []) if isinstance(item, dict)]
    materials = {
        item.get("local_id"): item for item in payload.get("materials", [])
        if isinstance(item, dict) and item.get("local_id")
    }
    assertions = []
    for expected in gold["rows"]:
        candidates = []
        for experiment in experiments:
            material = materials.get(_material_ref(experiment), {})
            for measurement in _measurements(experiment):
                if measurement.get("property") != "vickers_hardness":
                    continue
                if (
                    measurement.get("raw_value") == expected["raw_value"]
                    and _number(measurement.get("value")) == float(expected["value"])
                    and str(measurement.get("unit", "")).strip().casefold() == "hv"
                    and _number(measurement.get("uncertainty")) == float(expected["uncertainty"])
                ):
                    candidates.append((experiment, material, measurement, _conditions(measurement)))
        association = [item for item in candidates if (
            expected["sample"].casefold() in str(item[1].get("name", "")).casefold()
            and _number(item[3].get("cooling_rate")) == float(expected["cooling_rate_c_per_s"])
            and str(item[3].get("hardness_scale", "")).casefold() == "vickers"
            and _number(item[3].get("test_load_kgf")) == 0.5
            and _number(item[3].get("number_of_indents")) == 5
            and item[3].get("dwell_time") == "not_reported"
        )]
        scientific = [item for item in association if item[3].get("scientific_type") == "reported_measurement"]
        ownership = [item for item in scientific if (
            item[0].get("ownership") == "focal_work" and item[1].get("ownership") == "focal_work"
        )]
        evidence = [item for item in ownership if _evidence_complete(item[2])]
        assertions.append({
            "table_row": expected["table_row"], "sample": expected["sample"],
            "value_correct": bool(candidates), "association_correct": bool(association),
            "scientific_type_correct": bool(scientific), "ownership_correct": bool(ownership),
            "source_tracked": bool(evidence), "passed": bool(evidence),
        })
    total = len(assertions)
    non_vickers_outputs = sum(
        measurement.get("property") != "vickers_hardness"
        or str(measurement.get("unit", "")).strip().casefold() != "hv"
        for experiment in experiments for measurement in _measurements(experiment)
    )
    return {
        "case_id": gold["case_id"], "schema_valid": False,
        "passed": sum(item["passed"] for item in assertions), "total": total,
        "overall": sum(item["passed"] for item in assertions) / total,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "association_accuracy": sum(item["association_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "ownership_accuracy": sum(item["ownership_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "non_vickers_or_converted_outputs": non_vickers_outputs,
        "assertions": assertions,
    }
