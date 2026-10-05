"""Frozen-gold scorer for AM-MICRO-C."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_micro_c(archive, gold: dict) -> dict:
    materials = {m.name: m for m in archive.materials}
    processes_by_output: dict[str, list] = {}
    for process in archive.processes:
        for output in process.outputs:
            processes_by_output.setdefault(output, []).append(process)
    assertions = []
    for expected in gold["rows"]:
        sample = expected["sample"]
        specimen = materials.get(f"{sample} SLM SS316L specimen")
        experiment = next((e for e in archive.experiments if specimen and e.material_ids == [specimen.material_id]), None)
        linked = processes_by_output.get(specimen.material_id, []) if specimen else []
        build = next((p for p in linked if p.family == "laser_powder_bed_fusion"), None)
        post = next((p for p in linked if p.family == "post_processing"), None)
        values = {m.conditions.get("crystal_plane"): m.value for m in experiment.outputs} if experiment else {}
        texture = values == dict(zip(gold["crystal_planes"], expected["values"], strict=True))
        evidence = bool(experiment and all(m.evidence and m.evidence[0].page == 9 and m.evidence[0].table_id == "Table 3" for m in experiment.outputs))
        orientation = sample.split("-")[1]
        params = {m.property: m for m in build.parameters} if build else {}
        build_ok = bool(build and params.get("build_orientation") and params["build_orientation"].value == f"{orientation}°")
        post_ok = (post is None) if sample.startswith("UHT") else bool(post and post.sequence_index > build.sequence_index)
        assertions.append({"sample": sample, "texture": texture, "evidence": evidence, "build": build_ok, "post_lineage": post_ok, "passed": all((texture, evidence, build_ok, post_ok))})
    properties = {m.property for e in archive.experiments for m in e.outputs}
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"], "passed": sum(a["passed"] for a in assertions), "total": len(assertions),
        "value_count": sum(len(e.outputs) for e in archive.experiments), "assertions": assertions,
        "scientific_safety": {
            "texture_is_crystallographic_not_surface": properties == {"texture_coefficient"},
            "no_phase_fraction_inferred": "phase_fraction" not in properties,
            "no_particle_grain_size_conflation": not properties.intersection({"grain_size", "cell_spacing"}),
            "post_process_separate": sum(p.family == "post_processing" for p in archive.processes) == 12,
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes),
        "experiments": len(archive.experiments), "analytics_rows": len(analytics),
    }
