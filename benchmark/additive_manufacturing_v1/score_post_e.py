"""Frozen-gold scorer for AM-POST-E."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_post_e(archive, gold: dict) -> dict:
    assertions = []
    processes_by_output = {output: process for process in archive.processes for output in process.outputs}
    for expected in gold["rows"]:
        specimen = next((m for m in archive.materials if m.name.startswith(expected["sample"] + " ") and ("post-processed" in m.name or expected["treatment"] == "AB")), None)
        experiment = next((e for e in archive.experiments if specimen and e.material_ids == [specimen.material_id]), None)
        outputs = {item.property: item for item in experiment.outputs} if experiment else {}
        mechanical = bool(
            outputs.get("yield_strength") and outputs["yield_strength"].value == expected["yield_strength_mpa"]
            and outputs.get("ultimate_tensile_strength") and outputs["ultimate_tensile_strength"].value == expected["uts_mpa"]
            and outputs.get("elongation") and outputs["elongation"].value == expected["elongation"]
        )
        chain = []
        current = specimen.material_id if specimen else None
        while current in processes_by_output:
            process = processes_by_output[current]
            chain.append(process)
            current = process.inputs[0] if process.inputs else None
        build = next((p for p in chain if p.family == "directed_energy_deposition"), None)
        post = [p for p in chain if p.family == "post_processing"]
        parameters = {p.property: p for p in build.parameters} if build else {}
        build_ok = bool(build and parameters.get("laser_power") and parameters["laser_power"].value == 425 and parameters.get("build_orientation") and parameters["build_orientation"].value == expected["orientation"])
        expected_steps = len(gold["treatments"][expected["treatment"]]["steps"])
        post_ok = len(post) == expected_steps
        evidence = bool(experiment and all(item.evidence and item.evidence[0].page == 8 and item.evidence[0].table_id == "Table 4" for item in experiment.outputs))
        assertions.append({"sample": expected["sample"], "build": build_ok, "post_lineage": post_ok, "mechanical": mechanical, "evidence": evidence, "passed": all((build_ok, post_ok, mechanical, evidence))})
    properties = {o.property for e in archive.experiments for o in e.outputs}
    return {
        "case_id": gold["case_id"], "passed": sum(a["passed"] for a in assertions), "total": len(assertions),
        "mechanical_value_count": sum(len(e.outputs) for e in archive.experiments), "assertions": assertions,
        "scientific_safety": {
            "as_built_has_no_post_process": all(a["post_lineage"] for a in assertions if a["sample"].endswith("_AB")),
            "treatment_identities_distinct": {p.name for p in archive.processes if p.family == "post_processing"} == {"solid-solution treatment and water quench", "direct aging and air cooling"},
            "mechanical_vocabulary_reused": properties == {"yield_strength", "ultimate_tensile_strength", "elongation"},
            "no_am_mechanical_duplicates": not any(name.startswith("am_") for name in properties),
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes), "experiments": len(archive.experiments), "calculations": len(archive.calculations), "analytics_rows": len(project_archives([archive])),
    }
