"""Frozen-gold scorer for AM-DENS-B."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_dens_b(archive, gold: dict) -> dict:
    processes_by_output = {
        output: process for process in archive.processes for output in process.outputs
    }
    assertions = []
    for expected in gold["rows"]:
        specimen = next((m for m in archive.materials if m.name == f'sample {expected["sample"]} LPBF 316L specimen'), None)
        experiment = next((e for e in archive.experiments if specimen and e.material_ids == [specimen.material_id]), None)
        build = processes_by_output.get(specimen.material_id) if specimen else None
        params = {p.property: p for p in build.parameters} if build else {}
        output = experiment.outputs[0] if experiment and len(experiment.outputs) == 1 else None
        coordinates = bool(build and all((
            params.get("laser_power") and params["laser_power"].value == expected["laser_power_w"],
            params.get("scan_speed") and params["scan_speed"].value == expected["scan_speed_mm_s"],
            params.get("hatch_spacing") and params["hatch_spacing"].value == expected["hatch_spacing_mm"],
            params.get("rotation_angle") and params["rotation_angle"].value == expected["rotation_angle_deg"],
            params.get("volumetric_energy_density") and params["volumetric_energy_density"].value == expected["volumetric_energy_density_j_mm3"],
        )))
        result = bool(output and output.property == "relative_density" and output.value == expected["relative_density_pct"] and output.unit == "%")
        evidence = bool(output and output.evidence and output.evidence[0].page == 8 and output.evidence[0].table_id == "Table 4")
        lineage = bool(build and build.inputs and build.outputs == [specimen.material_id])
        assertions.append({"sample": expected["sample"], "coordinates": coordinates, "result": result, "evidence": evidence, "lineage": lineage, "passed": all((coordinates, result, evidence, lineage))})
    properties = {m.property for p in archive.processes for m in p.parameters} | {m.property for e in archive.experiments for m in e.outputs}
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"], "passed": sum(a["passed"] for a in assertions),
        "total": len(assertions), "assertions": assertions,
        "coordinate_accuracy": sum(a["coordinates"] for a in assertions) / len(assertions),
        "value_accuracy": sum(a["result"] for a in assertions) / len(assertions),
        "evidence_accuracy": sum(a["evidence"] for a in assertions) / len(assertions),
        "lineage_accuracy": sum(a["lineage"] for a in assertions) / len(assertions),
        "scientific_safety": {
            "relative_density_not_converted": not properties.intersection({"porosity", "absolute_density", "void_fraction"}),
            "reported_ved_only": "volumetric_energy_density" in properties and not properties.intersection({"linear_energy_density", "surface_energy_density"}),
            "defect_identities_distinct": all(key in archive.domain_payloads[0].values["defect_identity"] for key in ("sample_2", "sample_3", "sample_4")),
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes),
        "experiments": len(archive.experiments), "analytics_rows": len(analytics),
    }
