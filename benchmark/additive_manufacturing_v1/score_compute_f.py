"""Frozen-gold scorer for AM-COMPUTE-F."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_compute_f(archive, gold: dict) -> dict:
    assertions = []
    for expected in gold["rows"]:
        material = next((m for m in archive.materials if expected["material"].casefold() in m.name.casefold()), None)
        calculation = next((c for c in archive.calculations if material and c.material_ids == [material.material_id]), None)
        params = {p.property: p for p in calculation.parameters} if calculation else {}
        output = calculation.outputs[0] if calculation and len(calculation.outputs) == 1 else None
        coordinates = bool(calculation and all((
            params.get("laser_power") and params["laser_power"].value == expected["laser_power_w"],
            params.get("scan_speed") and params["scan_speed"].value == expected["scan_speed_mm_s"],
            params.get("spot_size") and params["spot_size"].value == expected["spot_size_um"],
            params.get("layer_thickness") and params["layer_thickness"].value == expected["layer_thickness_um"],
        )))
        result = bool(output and output.property == "melt_pool_width" and output.value == expected["predicted_melt_pool_width_um"] and output.unit == "µm" and output.conditions.get("scientific_type") == "simulation_result")
        validation = bool(output and output.conditions.get("validation_measurement_um") == expected["measured_melt_pool_width_um"] and output.conditions.get("validation_uncertainty_um") == expected["measured_uncertainty_um"])
        evidence = bool(output and output.evidence and output.evidence[0].page == 23 and output.evidence[0].table_id == "Table 3")
        assertions.append({"material": expected["material"], "coordinates": coordinates, "calculated_result": result, "validation_context": validation, "evidence": evidence, "passed": all((coordinates, result, validation, evidence))})
    return {
        "case_id": gold["case_id"], "passed": sum(a["passed"] for a in assertions), "total": len(assertions), "assertions": assertions,
        "scientific_safety": {
            "calculation_records_only": len(archive.calculations) == len(assertions) and not archive.experiments,
            "predicted_not_promoted_to_measured": all(c.outputs[0].conditions.get("scientific_type") == "simulation_result" for c in archive.calculations),
            "measured_values_are_validation_context_only": not archive.experiments and all("validation_measurement_um" in c.outputs[0].conditions for c in archive.calculations),
            "melt_pool_depth_not_invented": all(o.property != "melt_pool_depth" for c in archive.calculations for o in c.outputs),
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes), "experiments": len(archive.experiments), "calculations": len(archive.calculations), "analytics_rows": len(project_archives([archive])),
    }
