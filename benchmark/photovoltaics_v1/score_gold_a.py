"""Frozen-gold scorer for PV-GOLD-A."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def score_gold_a(archive, gold: dict) -> dict:
    devices = {item.configuration.get("variant"): item for item in archive.devices}
    processes_by_device = {
        output: process
        for process in archive.processes
        for output in process.outputs
        if output in {device.device_id for device in archive.devices}
    }
    experiments_by_device = {
        experiment.device_id: experiment for experiment in archive.experiments
    }
    materials = {item.material_id: item for item in archive.materials}
    assertions = []
    for expected in gold["rows"]:
        variant = expected["variant"]
        device = devices.get(variant)
        experiment = experiments_by_device.get(device.device_id) if device else None
        process = processes_by_device.get(device.device_id) if device else None
        outputs = {item.property: item for item in experiment.outputs} if experiment else {}
        values_correct = bool(experiment and len(outputs) == 5 and all(
            property_name in outputs
            and outputs[property_name].value == values[0]
            and outputs[property_name].uncertainty == values[1]
            and outputs[property_name].unit == values[2]
            and outputs[property_name].uncertainty_unit == values[2]
            for property_name, values in expected.items()
            if property_name in {
                "open_circuit_voltage", "short_circuit_current",
                "short_circuit_current_density", "fill_factor",
                "power_conversion_efficiency",
            }
        ))
        conditions_correct = bool(outputs and all(
            measurement.conditions.get("illumination_spectrum") == "AM 1.5 G"
            and measurement.conditions.get("irradiance") == 100.0
            and measurement.conditions.get("irradiance_unit") == "mW/cm2"
            and measurement.conditions.get("active_area") == "not reported"
            and measurement.conditions.get("scan_direction") == "not reported"
            and measurement.conditions.get("scientific_type") == "reported_measurement"
            for measurement in outputs.values()
        ))
        stack = device.configuration.get("layer_stack", []) if device else []
        architecture_correct = bool(device and (
            [layer.get("sequence_index") for layer in stack] == list(range(6))
            and [layer.get("role") for layer in stack]
            == ["substrate", "transparent_electrode", "etl", "absorber", "htl", "electrode"]
            and all(layer.get("material_id") in materials for layer in stack)
            and len(device.material_ids) == 6
        ))
        process_parameters = {item.property: item for item in process.parameters} if process else {}
        expected_time = expected["treatment_time_min"]
        process_correct = bool(process and device.device_id in process.outputs and (
            (expected_time is None and not process_parameters)
            or (
                expected_time is not None
                and process_parameters.get("processing_time") is not None
                and process_parameters["processing_time"].value == expected_time
                and process_parameters["processing_time"].unit == "min"
            )
        ))
        evidence_correct = bool(outputs and all(
            measurement.raw_value
            and measurement.evidence
            and all(
                evidence.page == 8
                and evidence.table_id
                and evidence.verbatim_match is True
                and measurement.raw_value in (evidence.text_snippet or "")
                and f"row={expected['label']}" in (evidence.locator or "")
                for evidence in measurement.evidence
            )
            for measurement in outputs.values()
        ))
        passed = all((values_correct, conditions_correct, architecture_correct, process_correct, evidence_correct))
        assertions.append({
            "variant": variant,
            "values_correct": values_correct,
            "conditions_correct": conditions_correct,
            "architecture_correct": architecture_correct,
            "process_correct": process_correct,
            "source_tracked": evidence_correct,
            "passed": passed,
        })

    analytics = project_archives([archive])
    analytics_safe = bool(len(analytics) == 20 and all(
        row.device_id
        and row.conditions.get("illumination_spectrum") == "AM 1.5 G"
        and row.conditions.get("irradiance") == 100.0
        and row.conditions.get("active_area") == "not reported"
        and len(row.conditions.get("device_layer_stack", [])) == 6
        for row in analytics
    ))
    canonical_properties = {
        output.property for experiment in archive.experiments for output in experiment.outputs
    }
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions),
        "assertions": assertions,
        "value_accuracy": sum(item["values_correct"] for item in assertions) / len(assertions),
        "condition_accuracy": sum(item["conditions_correct"] for item in assertions) / len(assertions),
        "architecture_accuracy": sum(item["architecture_correct"] for item in assertions) / len(assertions),
        "process_accuracy": sum(item["process_correct"] for item in assertions) / len(assertions),
        "source_tracking": sum(item["source_tracked"] for item in assertions) / len(assertions),
        "scientific_safety": {
            "analytics_preserve_device_and_context": analytics_safe,
            "active_area_not_inferred": all(
                output.conditions.get("active_area") == "not reported"
                for experiment in archive.experiments for output in experiment.outputs
            ),
            "percent_properties_preserved": all(
                output.unit == "%"
                for experiment in archive.experiments for output in experiment.outputs
                if output.property in {"fill_factor", "power_conversion_efficiency"}
            ),
            "property_identity_preserved": canonical_properties == {
                "open_circuit_voltage", "short_circuit_current",
                "short_circuit_current_density", "fill_factor",
                "power_conversion_efficiency",
            },
            "quarantine_count": len(quarantine),
        },
        "materials": len(archive.materials),
        "devices": len(archive.devices),
        "processes": len(archive.processes),
        "experiments": len(archive.experiments),
        "outputs": sum(len(item.outputs) for item in archive.experiments),
        "analytics_rows": len(analytics),
    }
