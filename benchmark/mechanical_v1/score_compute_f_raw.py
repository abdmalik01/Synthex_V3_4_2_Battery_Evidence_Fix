"""Semantic score for an immutable raw MECH-COMPUTE-F provider payload."""

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


def _outputs(calculation: dict) -> list[dict]:
    value = calculation.get("outputs", calculation.get("measurements"))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [calculation] if calculation.get("property") else []


def _conditions(output: dict) -> dict[str, Any]:
    value = output.get("conditions", {})
    if isinstance(value, dict):
        return value
    result = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                result[item["name"]] = item.get("value", item.get("raw_value"))
    return result


def _material_ref(calculation: dict, output: dict) -> str | None:
    if output.get("material_id"):
        return output["material_id"]
    if calculation.get("material_id"):
        return calculation["material_id"]
    refs = calculation.get("material_refs", [])
    return refs[0] if isinstance(refs, list) and len(refs) == 1 else None


def _evidence_complete(output: dict) -> bool:
    evidence = output.get("evidence")
    if evidence is None and isinstance(output.get("source"), dict):
        evidence = [output["source"]]
    if isinstance(evidence, dict):
        evidence = [evidence]
    return isinstance(evidence, list) and any(
        isinstance(item, dict) and item.get("page") and item.get("table_id")
        and item.get("locator") and item.get("text_snippet")
        and item.get("verbatim_match") is True for item in evidence
    )


def score_raw_compute_payload(payload: dict, gold: dict) -> dict:
    calculations = [item for item in payload.get("calculations", []) if isinstance(item, dict)]
    experiments = [item for item in payload.get("experiments", []) if isinstance(item, dict)]
    materials = {
        item.get("local_id"): item for item in payload.get("materials", [])
        if isinstance(item, dict) and item.get("local_id")
    }
    assertions = []
    for expected in gold["rows"]:
        candidates = []
        for calculation in calculations:
            for output in _outputs(calculation):
                material = materials.get(_material_ref(calculation, output), {})
                if output.get("property") == expected["property"] and material.get("name") == expected["material"]:
                    candidates.append((calculation, material, output, _conditions(output)))
        values = [item for item in candidates if (
            item[2].get("raw_value") == expected["raw_value"]
            and _number(item[2].get("value", item[2].get("raw_value"))) == expected["value"]
            and str(item[2].get("unit", "")).casefold() == expected["unit"].casefold()
        )]
        scientific = [item for item in values if item[3].get("scientific_type") == "simulation_result"]
        method = [item for item in scientific if (
            str(item[0].get("code", item[0].get("software", ""))).casefold() == "castep"
            and "density functional" in str(item[0].get("method", "")).casefold()
        )]
        ownership = [item for item in method if (
            item[0].get("ownership") == "focal_work" and item[1].get("ownership") == "focal_work"
        )]
        evidence = [item for item in ownership if _evidence_complete(item[2])]
        assertions.append({
            "material": expected["material"], "property": expected["property"],
            "value_correct": bool(values), "scientific_type_correct": bool(scientific),
            "method_correct": bool(method), "ownership_correct": bool(ownership),
            "source_tracked": bool(evidence), "passed": bool(evidence),
        })
    total = len(assertions)
    experimental_mechanical_outputs = sum(
        len(item.get("outputs", item.get("measurements", [])))
        for item in experiments if isinstance(item.get("outputs", item.get("measurements", [])), list)
    )
    return {
        "case_id": gold["case_id"], "schema_valid": False,
        "passed": sum(item["passed"] for item in assertions), "total": total,
        "overall": sum(item["passed"] for item in assertions) / total,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "method_accuracy": sum(item["method_correct"] for item in assertions) / total,
        "ownership_accuracy": sum(item["ownership_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "calculation_count": len(calculations), "experiment_count": len(experiments),
        "experimental_mechanical_outputs": experimental_mechanical_outputs,
        "assertions": assertions,
    }
