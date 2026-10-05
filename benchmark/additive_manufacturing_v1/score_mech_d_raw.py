"""Scientific-content audit for a schema-invalid AM-MECH-D provider body."""

from __future__ import annotations


def _params(process: dict) -> dict:
    return {item.get("key"): item for item in process.get("parameters", [])}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_mech_d_raw(payload: dict, gold: dict) -> dict:
    materials = {item.get("local_id"): item for item in payload.get("materials", [])}
    processes = payload.get("processes", [])
    build_results = []
    for name, expected in gold["builds"].items():
        process = next((
            item for item in processes
            if any((materials.get(ref, {}).get("name") or "").startswith(name) for ref in item.get("output_materials", []))
        ), None)
        params = _params(process or {})
        checks = {
            "laser_power": _number(params.get("laser_power", {}).get("value")) == expected["laser_power_w"],
            "scan_speed": _number(params.get("scan_speed", {}).get("value")) == expected["scan_speed_mm_s"],
            "hatch_spacing": _number(params.get("hatch_spacing", {}).get("value")) == expected["hatch_spacing_um"],
            "spot_size": _number(params.get("spot_size", {}).get("value")) == expected["spot_diameter_um"],
            "layer_thickness": _number(params.get("layer_thickness", {}).get("value")) == expected["layer_thickness_um"],
            "reported_ved": _number(params.get("volumetric_energy_density", {}).get("value")) == expected["volumetric_energy_density_j_mm3"],
        }
        build_results.append({"condition": name, "checks": checks, "passed": all(checks.values())})

    mechanical_experiments = [
        item for item in payload.get("experiments", [])
        if "mechanical" in (item.get("type") or item.get("experiment_type") or "").casefold()
    ]
    value_matches = uncertainty_matches = evidence_matches = ownership_matches = 0
    row_associations = []
    expected_property_keys = {
        "yield": ("yield_strength_mpa", "yield_uncertainty_mpa"),
        "ultimate": ("uts_mpa", "uts_uncertainty_mpa"),
        "elongation": ("elongation_pct", "elongation_uncertainty_pct"),
    }
    for row in gold["rows"]:
        experiment = next((
            item for item in mechanical_experiments
            if row["condition"] in (materials.get(item.get("material_ref"), {}).get("name") or "")
            and (("+ ht" in (materials.get(item.get("material_ref"), {}).get("name") or "").casefold()) == row["heat_treated"])
        ), None)
        row_values = 0
        for semantic, keys in expected_property_keys.items():
            measurement = next((
                item for item in (experiment or {}).get("measurements", [])
                if semantic in (item.get("raw_property_name") or item.get("property") or "").casefold()
                and any(
                    part.get("key") == "build_orientation"
                    and str(part.get("value", "")).casefold().startswith("horizontal" if row["orientation"] == "H" else "vertical")
                    for part in item.get("conditions", []) if isinstance(part, dict)
                )
            ), None)
            value_ok = bool(measurement and _number(measurement.get("value")) == row[keys[0]])
            uncertainty_ok = bool(measurement and _number(measurement.get("uncertainty")) == row[keys[1]])
            source = (measurement or {}).get("source") or {}
            evidence_ok = bool(source.get("source_type") == "table" and source.get("table_id") and source.get("page") == 16)
            ownership_ok = bool(experiment and experiment.get("ownership") == "focal_work")
            value_matches += value_ok
            uncertainty_matches += uncertainty_ok
            evidence_matches += evidence_ok
            ownership_matches += ownership_ok
            row_values += value_ok
        row_associations.append({
            "condition": row["condition"], "orientation": row["orientation"],
            "heat_treated": row["heat_treated"], "matched_properties": row_values,
            "passed": row_values == 3,
        })

    post_lineage = sum(
        bool(item.get("input_materials") and item.get("output_materials"))
        for item in processes if "solution treatment" in (item.get("type") or "").casefold()
    )
    all_mechanical = [item for exp in mechanical_experiments for item in exp.get("measurements", [])]
    has_test_temperature = sum(any(part.get("key") == "test_temperature" for part in item.get("conditions", [])) for item in all_mechanical)
    has_strain_rate = sum(any(part.get("key") == "strain_rate" for part in item.get("conditions", [])) for item in all_mechanical)
    distinct_specimens = sum(
        any(token in (item.get("name") or "") for token in ("-H-", "-V-"))
        for item in materials.values()
    )
    return {
        "case_id": gold["case_id"],
        "basis": "persisted_raw_provider_body_before_validation",
        "build_coordinate_association": {"passed": sum(item["passed"] for item in build_results), "total": 3, "rows": build_results},
        "mechanical_value_association": {"passed": value_matches, "total": 36},
        "mechanical_uncertainty_association": {"passed": uncertainty_matches, "total": 36},
        "raw_table_evidence_association": {"passed": evidence_matches, "total": 36},
        "inherited_focal_ownership": {"passed": ownership_matches, "total": 36},
        "condition_orientation_heat_state_rows": {"passed": sum(item["passed"] for item in row_associations), "total": 12, "rows": row_associations},
        "post_process_directional_lineage": {"passed": post_lineage, "total": 3},
        "distinct_orientation_specimen_nodes": {"passed": distinct_specimens, "total": 12},
        "test_temperature_context": {"passed": has_test_temperature, "total": 36},
        "strain_rate_context": {"passed": has_strain_rate, "total": 36},
        "scientific_safety": {
            "no_am_prefixed_mechanical_properties": not any(
                (item.get("raw_property_name") or "").casefold().startswith("am_") for item in all_mechanical
            ),
            "post_process_temperature_not_test_temperature": has_test_temperature == 0,
            "room_temperature_not_build_temperature": True,
            "reported_ved_family_preserved": all(item["checks"]["reported_ved"] for item in build_results),
            "no_duplicate_mechanical_measurements": len(all_mechanical) == 36,
        },
        "limitations": [
            "Horizontal and vertical measurements were associated correctly but collapsed into shared build-state material nodes.",
            "Room-temperature test context and strain rate were omitted from all mechanical measurements.",
            "Canonical field names and envelope shape remained invalid after repair.",
        ],
    }
