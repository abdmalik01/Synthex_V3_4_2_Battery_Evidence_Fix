"""Score provider Creep semantics without admitting its invalid JSON to the archive."""

from __future__ import annotations


_EXPECTED = (
    ("rupture_time_h", "rupture_time", "h"),
    ("rupture_strain_percent", "rupture_strain", "%"),
    ("time_to_1_percent_h", "time_to_specific_strain", "h"),
)


def _conditions(measurement: dict) -> dict:
    result = {}
    for item in measurement.get("conditions", []):
        if isinstance(item, dict) and item.get("name"):
            result[item["name"]] = item.get("value", item.get("raw_value"))
    return result


def score_raw_creep_payload(payload: dict, gold: dict) -> dict:
    """Keep semantic accuracy separate from schema/evidence admission failure."""
    experiments = payload.get("experiments") if isinstance(payload.get("experiments"), list) else []
    measurements = [
        item for experiment in experiments if isinstance(experiment, dict)
        for item in experiment.get("measurements", []) if isinstance(item, dict)
    ]
    materials = {
        item.get("local_id"): item for item in payload.get("materials", [])
        if isinstance(item, dict) and item.get("local_id")
    }
    results = []
    for row in gold["rows"]:
        for key, property_name, unit in _EXPECTED:
            raw, value = row[key], float(row[key])
            candidates = [item for item in measurements if item.get("property") == property_name]
            value_rows = [item for item in candidates if (
                item.get("raw_value") == raw and item.get("value") == value and item.get("unit") == unit
            )]
            associated = [item for item in value_rows if (
                _conditions(item).get("temperature") == row["test_temperature_c"]
                and _conditions(item).get("applied_stress") == row["applied_stress_mpa"]
            )]
            scientific = [item for item in associated if (
                _conditions(item).get("scientific_type") == "reported_measurement"
            )]
            parent = next((experiment for experiment in experiments if any(
                item is candidate for candidate in experiment.get("measurements", [])
                for item in scientific
            )), None)
            material = materials.get(parent.get("material_id")) if parent else None
            sample_ok = bool(material and "diffusion-welded alloy 617" in str(material.get("name", "")).casefold())
            process_ok = bool(material and set(material.get("processing_history", [])) >= {"process_1", "process_2"})
            ownership_ok = bool(parent and material and parent.get("ownership") == "focal_work" and material.get("ownership") == "focal_work")
            source_rows = [item for item in scientific if isinstance(item.get("source"), dict)]
            # A table ID alone is not value-specific evidence: no page, snippet,
            # row/cell locator, or independently verified verbatim flag exists.
            evidence_ok = any(all(item["source"].get(key) for key in (
                "page", "text_snippet", "locator", "verbatim_match",
            )) for item in source_rows)
            passed = bool(scientific and sample_ok and process_ok and ownership_ok and evidence_ok)
            results.append({
                "table_row": row["table_row"], "property": property_name,
                "value_correct": bool(value_rows), "test_condition_correct": bool(associated),
                "scientific_type_correct": bool(scientific), "sample_correct": sample_ok,
                "processing_correct": process_ok, "ownership_correct": ownership_ok,
                "source_tracked": evidence_ok, "passed": passed,
            })
    excluded_checks = []
    for row in gold["excluded_source_rows"]:
        admitted = any(
            _conditions(item).get("temperature") == row["test_temperature_c"]
            and _conditions(item).get("applied_stress") == row["applied_stress_mpa"]
            for item in measurements
        )
        excluded_checks.append({**row, "incorrectly_extracted": admitted})
    total = len(results)
    return {
        "case_id": gold["case_id"], "schema_valid": False,
        "passed": sum(item["passed"] for item in results), "total": total,
        "value_accuracy": sum(item["value_correct"] for item in results) / total,
        "test_condition_accuracy": sum(item["test_condition_correct"] for item in results) / total,
        "sample_accuracy": sum(item["sample_correct"] for item in results) / total,
        "processing_accuracy": sum(item["processing_correct"] for item in results) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in results) / total,
        "ownership_accuracy": sum(item["ownership_correct"] for item in results) / total,
        "source_tracking": sum(item["source_tracked"] for item in results) / total,
        "invalid_source_rows": excluded_checks,
        "invalid_source_row_rejection": sum(not item["incorrectly_extracted"] for item in excluded_checks) / len(excluded_checks),
        "assertions": results,
    }
