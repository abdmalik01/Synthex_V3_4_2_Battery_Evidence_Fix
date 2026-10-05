"""Score raw provider TE-GOLD-A JSON without granting canonical admission."""

from __future__ import annotations

import math
import re


_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _number_in_text(value):
    if not isinstance(value, str):
        return _number(value)
    match = _NUMBER.search(value.replace(",", ""))
    return float(match.group()) if match else None


def score_raw_gold_a(payload: dict, expected_series: dict[str, list[list[float]]], gold: dict) -> dict:
    outputs = []
    for experiment in payload.get("experiments", []) if isinstance(payload.get("experiments"), list) else []:
        if isinstance(experiment, dict) and isinstance(experiment.get("outputs"), list):
            outputs.extend(item for item in experiment["outputs"] if isinstance(item, dict))
    flat_outputs = payload.get("measurements", []) if isinstance(payload.get("measurements"), list) else []
    outputs.extend(item for item in flat_outputs if isinstance(item, dict))
    observed: dict[str, list[list[float]]] = {}
    for item in outputs:
        property_name = item.get("property") or item.get("canonical_property")
        conditions = item.get("conditions") if isinstance(item.get("conditions"), dict) else {}
        temperature = _number(conditions.get("temperature")) or _number_in_text(item.get("temperature"))
        value = _number(item.get("value")) or _number_in_text(item.get("raw_value"))
        if property_name in expected_series and temperature is not None and value is not None:
            observed.setdefault(property_name, []).append([temperature, value])

    series = {}
    for property_name, expected in expected_series.items():
        candidates = observed.get(property_name, [])
        matched = sum(
            1 for temperature, value in expected
            if any(
                math.isclose(temperature, candidate_temperature, rel_tol=0, abs_tol=1e-8)
                and math.isclose(value, candidate_value, rel_tol=0, abs_tol=1e-8)
                for candidate_temperature, candidate_value in candidates
            )
        )
        series[property_name] = {
            "expected_points": len(expected),
            "observed_points": len(candidates),
            "exact_points": matched,
            "recall": matched / len(expected),
        }

    materials = payload.get("materials") if isinstance(payload.get("materials"), list) else []
    material_match = any(
        isinstance(item, dict)
        and item.get("formula") == gold["material"]["formula"]
        and item.get("composition") == gold["material"]["composition"]
        for item in materials
    )
    parameters = []
    for process in payload.get("processes", []) if isinstance(payload.get("processes"), list) else []:
        if isinstance(process, dict) and isinstance(process.get("parameters"), list):
            parameters.extend(item for item in process["parameters"] if isinstance(item, dict))
    for process in payload.get("synthesis", []) if isinstance(payload.get("synthesis"), list) else []:
        if not isinstance(process, dict):
            continue
        for name in gold["process"]:
            if name in process:
                parameters.append({"property": name, "value": _number_in_text(process[name]), "unit": str(process[name]).split(maxsplit=1)[-1]})
    process_map = {item.get("property"): item for item in parameters}
    process_matches = sum(
        1 for name, (value, unit) in gold["process"].items()
        if name in process_map
        and _number(process_map[name].get("value")) == value
        and process_map[name].get("unit") == unit
    )
    seebeck = [item for item in outputs if (item.get("property") or item.get("canonical_property")) == "seebeck_coefficient"]
    signed_safe = bool(seebeck) and all(
        _number(item.get("value")) is not None
        and item["value"] > 0
        and isinstance(item.get("conditions"), dict)
        and item["conditions"].get("seebeck_sign") == "positive"
        and item["conditions"].get("absolute_value") is False
        for item in seebeck
    )
    total_expected = sum(len(points) for points in expected_series.values())
    total_exact = sum(item["exact_points"] for item in series.values())
    flat_measurements = [item for item in flat_outputs if isinstance(item, dict)]
    sample_association = bool(outputs) and all(item.get("material_ref") for item in outputs)
    temperature_association = bool(outputs) and all(
        _number((item.get("conditions") or {}).get("temperature")) is not None
        if isinstance(item.get("conditions"), dict) and "temperature" in item["conditions"]
        else _number_in_text(item.get("temperature")) is not None
        for item in outputs
    )
    evidence_locations = bool(outputs) and all(
        bool(item.get("locator")) or bool(item.get("evidence")) for item in outputs
    )
    scientific_type_explicit = bool(outputs) and all(
        isinstance(item.get("conditions"), dict) and bool(item["conditions"].get("scientific_type"))
        for item in outputs
    )
    return {
        "case_id": gold["case_id"],
        "series": series,
        "total_expected_points": total_expected,
        "total_exact_points": total_exact,
        "point_recall": total_exact / total_expected,
        "material_match": material_match,
        "process_parameter_matches": process_matches,
        "process_parameter_total": len(gold["process"]),
        "signed_seebeck_safe": signed_safe,
        "raw_output_count": len(outputs),
        "flat_measurement_count": len(flat_measurements),
        "sample_association_present": sample_association,
        "temperature_association_present": temperature_association,
        "evidence_locations_present": evidence_locations,
        "scientific_type_explicit": scientific_type_explicit,
        "canonical_admission_not_implied": True,
    }
