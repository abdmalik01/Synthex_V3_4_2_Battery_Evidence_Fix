"""Semantic score for an immutable raw MECH-FATIGUE-C provider payload."""

from __future__ import annotations

import math
from typing import Any


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


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _condition(conditions: dict, *names: str):
    for name in names:
        if name in conditions:
            return conditions[name]
    return None


def _outcome(conditions: dict) -> str | None:
    value = _condition(conditions, "failure_or_runout", "failure_status", "outcome")
    return str(value).strip().casefold().replace("-", "") if value is not None else None


def _evidence_complete(measurement: dict) -> bool:
    evidence = measurement.get("evidence")
    if evidence is None and isinstance(measurement.get("source"), dict):
        evidence = [measurement["source"]]
    if isinstance(evidence, dict):
        evidence = [evidence]
    if not isinstance(evidence, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("page")
        and item.get("table_id")
        and item.get("locator")
        and item.get("text_snippet")
        and item.get("verbatim_match") is True
        for item in evidence
    )


def score_raw_fatigue_payload(payload: dict, gold: dict) -> dict:
    experiments = [item for item in payload.get("experiments", []) if isinstance(item, dict)]
    materials = {
        item.get("local_id"): item for item in payload.get("materials", [])
        if isinstance(item, dict) and item.get("local_id")
    }
    assertions = []
    runout_checks = []
    matched_objects: set[int] = set()
    for row in gold["rows"]:
        expected = [("stress_amplitude", row["stress_amplitude_mpa"], float(row["stress_amplitude_mpa"]))]
        if row["outcome"] == "failure":
            expected.append((
                "cycles_to_failure", row["cycles_to_failure"],
                float(row["cycles_to_failure"].replace(",", "")),
            ))
        row_matches = []
        for property_name, raw_value, numeric_value in expected:
            candidates = []
            for experiment in experiments:
                material = materials.get(_material_ref(experiment), {})
                for measurement in _measurements(experiment):
                    if measurement.get("property") != property_name:
                        continue
                    if measurement.get("raw_value") != raw_value or _number(measurement.get("value")) != numeric_value:
                        continue
                    conditions = _conditions(measurement)
                    candidates.append((experiment, material, measurement, conditions))
            condition_matches = []
            for experiment, material, measurement, conditions in candidates:
                orientation = _condition(conditions, "orientation", "specimen_orientation")
                frequency = _number(_condition(conditions, "test_frequency_rpm", "frequency_rpm", "frequency"))
                ratio = _number(_condition(conditions, "stress_ratio", "r_ratio", "R"))
                outcome = _outcome(conditions)
                if (
                    str(orientation).casefold() == row["orientation"]
                    and frequency == float(row["test_frequency_rpm"])
                    and ratio == float(gold["gold_basis"]["stress_ratio"])
                    and outcome == row["outcome"].replace("-", "")
                ):
                    condition_matches.append((experiment, material, measurement, conditions))
            sample_matches = [item for item in condition_matches if (
                gold["gold_basis"]["sample"].casefold() in str(item[1].get("name", "")).casefold()
            )]
            scientific_matches = [item for item in sample_matches if (
                _condition(item[3], "scientific_type") == "reported_measurement"
            )]
            ownership_matches = [item for item in scientific_matches if (
                item[0].get("ownership") == "focal_work" and item[1].get("ownership") == "focal_work"
            )]
            evidence_matches = [item for item in ownership_matches if _evidence_complete(item[2])]
            passed = bool(evidence_matches)
            selected = evidence_matches or ownership_matches or scientific_matches or sample_matches or condition_matches
            if selected:
                matched_objects.add(id(selected[0][2]))
                row_matches.append(selected[0])
            assertions.append({
                "table": row["table"], "table_row": row["table_row"], "property": property_name,
                "value_correct": bool(candidates), "condition_correct": bool(condition_matches),
                "sample_correct": bool(sample_matches), "scientific_type_correct": bool(scientific_matches),
                "ownership_correct": bool(ownership_matches), "source_tracked": bool(evidence_matches),
                "passed": passed,
            })
        if row["outcome"] == "runout":
            amplitude_match = next((item for item in row_matches if item[2].get("property") == "stress_amplitude"), None)
            safe = False
            if amplitude_match:
                experiment, _, amplitude, conditions = amplitude_match
                limit = _number(_condition(conditions, "runout_limit_cycles", "runout_cycles"))
                sibling_failure = any(
                    item.get("property") == "cycles_to_failure"
                    and _number(item.get("value")) == 10000000
                    and _outcome(_conditions(item)) == "runout"
                    for item in _measurements(experiment)
                )
                safe = _outcome(conditions) == "runout" and limit == 10000000 and not sibling_failure
            runout_checks.append({
                "table": row["table"], "table_row": row["table_row"], "censoring_correct": safe,
            })
    total = len(assertions)
    fatigue_limit_inventions = sum(
        measurement.get("property") == "fatigue_limit"
        for experiment in experiments for measurement in _measurements(experiment)
    )
    duplicate_227 = [
        measurement for experiment in experiments for measurement in _measurements(experiment)
        if measurement.get("property") == "stress_amplitude"
        and _number(measurement.get("value")) == 227.26
    ]
    return {
        "case_id": gold["case_id"], "schema_valid": False,
        "passed": sum(item["passed"] for item in assertions), "total": total,
        "overall": sum(item["passed"] for item in assertions) / total,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "row_condition_accuracy": sum(item["condition_correct"] for item in assertions) / total,
        "sample_accuracy": sum(item["sample_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "ownership_accuracy": sum(item["ownership_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "runout_checks": runout_checks,
        "runout_correctness": (
            sum(item["censoring_correct"] for item in runout_checks) / len(runout_checks)
            if runout_checks else None
        ),
        "fatigue_limit_inventions": fatigue_limit_inventions,
        "duplicate_227_26_observations": len(duplicate_227),
        "assertions": assertions,
    }
