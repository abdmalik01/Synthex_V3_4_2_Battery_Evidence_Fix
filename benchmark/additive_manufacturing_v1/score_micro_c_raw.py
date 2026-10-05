"""Scientific-content audit for a schema-invalid AM-MICRO-C provider body."""

from __future__ import annotations


def score_micro_c_raw(payload: dict, gold: dict) -> dict:
    materials = {item.get("local_id"): item for item in payload.get("materials", [])}
    expected_rows = {item["sample"]: item for item in gold["rows"]}
    specimen_matches = {
        sample: next((item for item in materials.values() if (item.get("name") or "").startswith(sample)), None)
        for sample in expected_rows
    }
    orientation_matches = sum(
        bool(material and (material.get("name") or "").startswith(sample))
        for sample, material in specimen_matches.items()
    )
    treatment_matches = sum(
        bool(material and (
            (sample.startswith("UHT") and "as-built" in (material.get("name") or "").casefold())
            or (not sample.startswith("UHT") and sample.split("-")[0].casefold() in (material.get("name") or "").casefold())
        ))
        for sample, material in specimen_matches.items()
    )
    material_to_sample = {
        material.get("local_id"): sample
        for sample, material in specimen_matches.items()
        if material
    }
    textures = [
        item for item in payload.get("measurements", [])
        if (item.get("property") or item.get("property_name") or "").casefold() == "texture_coefficient"
    ]
    value_matches = 0
    fully_associated = 0
    evidence_count = 0
    ownership_count = 0
    scientific_type_count = 0
    recovered: list[dict] = []
    for item in textures:
        sample = material_to_sample.get(item.get("material_id"))
        raw = item.get("raw_value")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        expected = expected_rows.get(sample, {}).get("values", [])
        matched_value = value in expected
        value_matches += matched_value
        conditions = item.get("conditions") or {}
        if isinstance(conditions, list):
            conditions = {part.get("key"): part.get("value") for part in conditions if isinstance(part, dict)}
        plane = conditions.get("crystal_plane") or conditions.get("plane") or conditions.get("index")
        plane_match = bool(
            matched_value and plane in gold["crystal_planes"]
            and expected[gold["crystal_planes"].index(plane)] == value
        )
        fully_associated += plane_match
        source = item.get("source") or {}
        has_evidence = bool(
            source.get("source_type") == "table"
            and source.get("table_id") and source.get("locator")
        )
        evidence_count += has_evidence
        ownership_count += bool(item.get("ownership"))
        scientific_type_count += bool(item.get("scientific_type"))
        recovered.append({
            "sample": sample, "value": value, "value_matches_gold": matched_value,
            "crystal_plane": plane, "fully_associated": plane_match,
            "raw_evidence_present": has_evidence,
        })
    process_types = [(item.get("type") or item.get("name") or "").casefold() for item in payload.get("processes", [])]
    return {
        "case_id": gold["case_id"],
        "basis": "persisted_raw_provider_body_before_validation_or_repair",
        "condition_identity": {"passed": sum(bool(item) for item in specimen_matches.values()), "total": 16},
        "orientation_identity": {"passed": orientation_matches, "total": 16},
        "heat_treatment_identity": {"passed": treatment_matches, "total": 16},
        "texture_value_recovery": {"passed": value_matches, "total": 80},
        "fully_associated_texture_values": {"passed": fully_associated, "total": 80},
        "raw_evidence_on_recovered_texture_values": {"passed": evidence_count, "total": len(textures)},
        "explicit_measurement_ownership": {"passed": ownership_count, "total": len(textures)},
        "explicit_scientific_type": {"passed": scientific_type_count, "total": len(textures)},
        "recovered_texture_values": recovered,
        "scientific_safety": {
            "crystallographic_texture_not_surface_texture": all("surface" not in (item.get("property") or "").casefold() for item in textures),
            "no_phase_fraction_inferred": not any("phase_fraction" in (item.get("property") or "").casefold() for item in payload.get("measurements", [])),
            "powder_particle_size_not_grain_size": not any(
                item.get("material_id") == "material_powder" and (item.get("property") or "").casefold() == "grain_size"
                for item in payload.get("measurements", [])
            ),
            "heat_treatment_separate_from_build": any("heat" in item or "solution" in item or "stress relief" in item for item in process_types),
            "per_specimen_post_process_lineage_preserved": False,
        },
        "limitations": [
            "Only one of 80 texture coefficients was returned.",
            "The recovered texture value has no crystallographic-plane index, so it is not a complete scientific association.",
            "Powder particle size was mislabeled as grain_size.",
            "Heat-treatment processes were not linked directionally to individual specimens.",
        ],
    }
