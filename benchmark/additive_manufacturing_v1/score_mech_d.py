"""Cross-domain scorer for AM-MECH-D."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_mech_d(archive, gold: dict) -> dict:
    materials = {m.name: m for m in archive.materials}
    linked_by_output: dict[str, list] = {}
    for process in archive.processes:
        for output in process.outputs:
            linked_by_output.setdefault(output, []).append(process)
    assertions = []
    measurement_ids = []
    for row in gold["rows"]:
        state = "HT" if row["heat_treated"] else "AB"
        label = f'{row["condition"]}-{row["orientation"]}-{state}'
        specimen = materials.get(f"{label} Inconel 625 tensile specimen")
        experiment = next((e for e in archive.experiments if specimen and e.material_ids == [specimen.material_id]), None)
        linked = linked_by_output.get(specimen.material_id, []) if specimen else []
        build = next((p for p in linked if p.family == "laser_powder_bed_fusion"), None)
        post = next((p for p in linked if p.family == "post_processing"), None)
        outputs = {m.property: m for m in experiment.outputs} if experiment else {}
        mechanical = bool(experiment and all((
            outputs.get("yield_strength") and outputs["yield_strength"].value == row["yield_strength_mpa"] and outputs["yield_strength"].uncertainty == row["yield_uncertainty_mpa"],
            outputs.get("ultimate_tensile_strength") and outputs["ultimate_tensile_strength"].value == row["uts_mpa"] and outputs["ultimate_tensile_strength"].uncertainty == row["uts_uncertainty_mpa"],
            outputs.get("elongation") and outputs["elongation"].value == row["elongation_pct"] and outputs["elongation"].uncertainty == row["elongation_uncertainty_pct"],
        )))
        expected_build = gold["builds"][row["condition"]]
        params = {m.property: m.value for m in build.parameters} if build else {}
        process = bool(build and params.get("scan_speed") == expected_build["scan_speed_mm_s"] and params.get("volumetric_energy_density") == expected_build["volumetric_energy_density_j_mm3"] and params.get("build_orientation") == row["orientation"])
        lineage = bool(build and build.inputs and build.outputs == [specimen.material_id] and ((not row["heat_treated"] and post is None) or (row["heat_treated"] and post and post.sequence_index > build.sequence_index)))
        evidence = bool(experiment and all(m.evidence and m.evidence[0].page == 16 and m.evidence[0].table_id == "Table 4" for m in experiment.outputs))
        if experiment:
            measurement_ids.extend((experiment.experiment_id, m.property, specimen.material_id) for m in experiment.outputs)
        assertions.append({"sample": label, "process": process, "mechanical": mechanical, "lineage": lineage, "evidence": evidence, "passed": all((process, mechanical, lineage, evidence))})
    properties = {m.property for e in archive.experiments for m in e.outputs}
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"], "passed": sum(a["passed"] for a in assertions), "total": len(assertions),
        "mechanical_value_count": sum(len(e.outputs) for e in archive.experiments), "assertions": assertions,
        "scientific_safety": {
            "mechanical_v1_vocabulary_reused": properties == {"yield_strength", "ultimate_tensile_strength", "elongation"},
            "no_am_mechanical_duplicates": not any(p.startswith("am_") for p in properties),
            "measurements_remain_specimen_scoped": len(measurement_ids) == len(set(measurement_ids)) == 36,
            "build_and_post_process_separate": sum(p.family == "post_processing" for p in archive.processes) == 6,
            "test_temperature_not_build_temperature": all("test_temperature" in m.conditions for e in archive.experiments for m in e.outputs),
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes),
        "experiments": len(archive.experiments), "analytics_rows": len(analytics),
    }
