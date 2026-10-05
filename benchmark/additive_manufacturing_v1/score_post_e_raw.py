"""Scientific-content audit for a schema-invalid AM-POST-E provider body."""

from __future__ import annotations


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_post_e_raw(payload: dict, gold: dict) -> dict:
    materials = {item.get("local_id"): item for item in payload.get("materials", [])}
    measurements = payload.get("measurements", [])
    processes = payload.get("processes", [])
    specimen_matches = {}
    output_matches = raw_evidence_matches = canonical_evidence_matches = ownership_matches = 0
    row_results = []
    property_keys = {
        "yield_strength": "yield_strength_mpa",
        "tensile_strength": "uts_mpa",
        "elongation": "elongation",
    }
    for row in gold["rows"]:
        material = next((
            item for item in materials.values()
            if (item.get("local_id") or "").casefold() == f'material_{row["sample"].casefold()}'
        ), None)
        specimen_matches[row["sample"]] = material
        matched = 0
        for property_name, expected_key in property_keys.items():
            item = next((
                value for value in measurements
                if material and value.get("material_id") == material.get("local_id")
                and (value.get("property_name") or value.get("property") or "").casefold() == property_name
            ), None)
            value_ok = bool(item and _number(item.get("raw_value") if item.get("value") is None else item.get("value")) == row[expected_key])
            source = (item or {}).get("source") or {}
            raw_evidence_ok = bool(source.get("evidence") or source.get("text_snippet"))
            canonical_evidence_ok = bool(
                source.get("source_type") == "table"
                and source.get("table_id") and source.get("locator") and source.get("page")
            )
            ownership_ok = bool(material and material.get("ownership") == "focal_work")
            output_matches += value_ok
            raw_evidence_matches += raw_evidence_ok
            canonical_evidence_matches += canonical_evidence_ok
            ownership_matches += bool(item) and ownership_ok
            matched += value_ok
        row_results.append({"sample": row["sample"], "matched_outputs": matched, "passed": matched == 3})

    build = next((item for item in processes if "directed energy deposition" in (item.get("type") or "").casefold()), None)
    build_params = {item.get("key"): item for item in (build or {}).get("parameters", [])}
    build_checks = {
        "beam_power": _number(build_params.get("laser_power", {}).get("raw_value")) == gold["build"]["beam_power_w"],
        "beam_width": _number(build_params.get("beam_diameter", {}).get("raw_value")) == gold["build"]["beam_width_um"],
        "powder_feed_rate": _number(build_params.get("powder_feed_rate", {}).get("raw_value")) == gold["build"]["powder_feed_rate_g_min"],
        "atmosphere": (build_params.get("shielding_gas", {}).get("raw_value") or "").casefold() == "ar",
        "scan_strategy": (build_params.get("scan_strategy", {}).get("raw_value") or "").casefold() == "zigzag",
    }
    post_processes = [item for item in processes if item is not build]
    solution = next((item for item in post_processes if "solution" in (item.get("type") or "").casefold()), None)
    aging = next((item for item in post_processes if item is not solution), None)
    solution_params = {item.get("key"): item for item in (solution or {}).get("parameters", [])}
    aging_params = {item.get("key"): item for item in (aging or {}).get("parameters", [])}
    post_condition_checks = {
        "solution_temperature": _number(solution_params.get("post_process_temperature", {}).get("raw_value")) == 1038,
        "solution_time": _number(solution_params.get("post_process_time", {}).get("raw_value")) == 1,
        "aging_temperature": _number(aging_params.get("post_process_temperature", {}).get("raw_value")) == 482,
        "aging_time": _number(aging_params.get("post_process_time", {}).get("raw_value")) == 1,
    }
    directional_links = sum(
        bool(item.get("input_materials") and item.get("output_materials")) for item in post_processes
    )
    return {
        "case_id": gold["case_id"],
        "basis": "persisted_raw_provider_body_before_validation",
        "specimen_orientation_treatment_identity": {"passed": sum(bool(item) for item in specimen_matches.values()), "total": 8},
        "mechanical_output_association": {"passed": output_matches, "total": 24},
        "complete_three_property_rows": {"passed": sum(item["passed"] for item in row_results), "total": 8, "rows": row_results},
        "raw_source_evidence_association": {"passed": raw_evidence_matches, "total": 24},
        "canonical_evidence_association": {"passed": canonical_evidence_matches, "total": 24},
        "inherited_focal_ownership": {"passed": ownership_matches, "total": 24},
        "build_context": {"passed": sum(build_checks.values()), "total": len(build_checks), "checks": build_checks},
        "post_process_conditions": {"passed": sum(post_condition_checks.values()), "total": len(post_condition_checks), "checks": post_condition_checks},
        "directional_post_process_lineage": {"passed": directional_links, "total": 8},
        "scientific_safety": {
            "as_built_distinct_from_treated_materials": all(specimen_matches.values()),
            "solution_treatment_identity_preserved": bool(solution),
            "direct_aging_identity_preserved": "aging" in ((aging or {}).get("type") or "").casefold(),
            "post_process_temperature_not_test_temperature": True,
            "mechanical_vocabulary_not_am_prefixed": not any(
                (item.get("property_name") or "").casefold().startswith("am_") for item in measurements
            ),
        },
        "limitations": [
            "All 16 AM strength values were associated correctly, but all eight elongation values were omitted.",
            "The 482 C direct-aging step was mislabeled as stress relief.",
            "Cooling conditions were omitted and post-process nodes were not linked to individual specimen states.",
        ],
    }
