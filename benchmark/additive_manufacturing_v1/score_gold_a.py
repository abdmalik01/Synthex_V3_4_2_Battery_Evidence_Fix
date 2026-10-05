"""Frozen-gold scorer for AM-GOLD-A."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def _parameters(process) -> dict:
    return {item.property: item for item in process.parameters}


def score_gold_a(archive, gold: dict) -> dict:
    materials = {item.material_id: item for item in archive.materials}
    feedstock = next((item for item in archive.materials if item.name == "pure tungsten powder"), None)
    feedstock_correct = bool(feedstock and feedstock.formula == "W" and all((
        feedstock.morphology.get("shape") == "spherical",
        feedstock.morphology.get("particle_size_d10_um") == 10.0,
        feedstock.morphology.get("particle_size_d50_um") == 15.87,
        feedstock.morphology.get("particle_size_d90_um") == 24.86,
    )))
    processes_by_output: dict[str, list] = {}
    for process in archive.processes:
        for material_id in process.outputs:
            processes_by_output.setdefault(material_id, []).append(process)

    assertions = []
    for expected in gold["rows"]:
        material = next((
            item for item in archive.materials
            if item.name == f'{expected["sample"]} as-built tungsten specimen'
        ), None)
        experiment = next((
            item for item in archive.experiments
            if material is not None and item.material_ids == [material.material_id]
        ), None)
        output = experiment.outputs[0] if experiment and len(experiment.outputs) == 1 else None
        linked = processes_by_output.get(material.material_id, []) if material else []
        build = next((item for item in linked if item.family == "laser_powder_bed_fusion"), None)
        post = next((item for item in linked if item.family == "post_processing"), None)
        parameters = _parameters(build) if build else {}
        values_correct = bool(output and (
            output.property == "relative_density"
            and output.value == expected["relative_density_pct"]
            and output.unit == "%"
            and output.conditions.get("scientific_type") == "reported_measurement"
            and output.conditions.get("reported_term") == "RD"
        ))
        coordinates_correct = bool(build and all((
            parameters.get("laser_power") and parameters["laser_power"].value == expected["laser_power_w"]
            and parameters["laser_power"].unit == "W",
            parameters.get("scan_speed") and parameters["scan_speed"].value == expected["scan_speed_mm_s"]
            and parameters["scan_speed"].unit == "mm/s",
            parameters.get("hatch_spacing") and parameters["hatch_spacing"].value == expected["hatch_spacing_mm"]
            and parameters["hatch_spacing"].unit == "mm",
            parameters.get("layer_thickness") and parameters["layer_thickness"].value == 0.03,
        )))
        build_context_correct = bool(build and all((
            build.equipment == "SLM 280HL",
            build.atmosphere == "high-purity argon; oxygen below 300 ppm",
            parameters.get("machine_model") and parameters["machine_model"].value == "SLM 280HL",
            parameters.get("shielding_gas") and parameters["shielding_gas"].value == "high-purity argon",
            parameters.get("chamber_oxygen") and parameters["chamber_oxygen"].value == 300.0,
            parameters.get("preheat_temperature") and parameters["preheat_temperature"].value == 423.15,
            parameters.get("scan_strategy") and parameters["scan_strategy"].value == "zigzag",
            parameters.get("rotation_angle") and parameters["rotation_angle"].value == 67.0,
            all(item.conditions.get("scientific_type") == "reported_process_parameter" for item in parameters.values()),
        )))
        lineage_correct = bool(
            material and build and post and build.inputs
            and materials[build.inputs[0]].name == "pure tungsten powder"
            and post.inputs == [material.material_id]
            and post.outputs == [material.material_id]
            and build.sequence_index < post.sequence_index
        )
        evidence_correct = bool(output and any(
            item.page == 4 and item.table_id and item.verbatim_match is True
            and item.text_snippet == output.raw_value
            and f'row={expected["sample"]};column=RD/(%)' in (item.locator or "")
            for item in output.evidence
        ) and build and all(
            measurement.evidence and all(
                item.page and item.verbatim_match is True and item.text_snippet
                and (item.locator or item.table_id)
                for item in measurement.evidence
            )
            for measurement in build.parameters
        ))
        assertions.append({
            "sample": expected["sample"], "value_correct": values_correct,
            "coordinates_correct": coordinates_correct, "lineage_correct": lineage_correct,
            "build_context_correct": build_context_correct,
            "feedstock_correct": feedstock_correct, "source_tracked": evidence_correct,
            "passed": all((values_correct, coordinates_correct, build_context_correct,
                           feedstock_correct, lineage_correct, evidence_correct)),
        })

    canonical_properties = {
        measurement.property
        for process in archive.processes for measurement in process.parameters
    } | {
        measurement.property
        for experiment in archive.experiments for measurement in experiment.outputs
    }
    analytics = project_archives([archive])
    analytic_coordinates = all(
        row.conditions.get("synthesis_laser_power") == expected["laser_power_w"]
        and row.conditions.get("synthesis_scan_speed") == expected["scan_speed_mm_s"]
        and row.conditions.get("synthesis_hatch_spacing") == expected["hatch_spacing_mm"]
        for row, expected in zip(
            sorted(analytics, key=lambda item: int((item.material_label or "T0").split()[0][1:])),
            gold["rows"], strict=True,
        )
    )
    total = len(assertions)
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions), "total": total,
        "assertions": assertions,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "coordinate_accuracy": sum(item["coordinates_correct"] for item in assertions) / total,
        "build_context_accuracy": sum(item["build_context_correct"] for item in assertions) / total,
        "feedstock_accuracy": sum(item["feedstock_correct"] for item in assertions) / total,
        "lineage_accuracy": sum(item["lineage_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "scientific_safety": {
            "relative_density_kept_distinct_from_porosity": "porosity" not in canonical_properties,
            "no_unreported_energy_density": not canonical_properties.intersection({
                "linear_energy_density", "surface_energy_density", "volumetric_energy_density",
            }),
            "analytics_preserve_build_coordinates": len(analytics) == 27 and analytic_coordinates,
            "quarantine_count": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        },
        "materials": len(archive.materials), "processes": len(archive.processes),
        "experiments": len(archive.experiments), "analytics_rows": len(analytics),
    }
