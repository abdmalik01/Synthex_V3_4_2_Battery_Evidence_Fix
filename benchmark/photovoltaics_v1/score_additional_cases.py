"""Frozen-gold scorers for PV-SPEC-B, PV-STAB-C, and PV-STACK-D."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives

from .case_common import canonical_digest


def _variant_devices(archive):
    return {device.configuration.get("variant"): device for device in archive.devices}


def _experiments_by_variant(archive):
    devices = {device.device_id: device.configuration.get("variant") for device in archive.devices}
    return {devices[experiment.device_id]: experiment for experiment in archive.experiments}


def _quarantine_count(archive) -> int:
    return len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])


def score_spec_b(archive, gold: dict) -> dict:
    devices = _variant_devices(archive)
    experiments = _experiments_by_variant(archive)
    assertions = []
    for expected in gold["series"]:
        variant = expected["variant"]
        device = devices.get(variant)
        experiment = experiments.get(variant)
        outputs = experiment.outputs if experiment else []
        points = [
            {"wavelength_nm": int(item.conditions["wavelength"]), "eqe_percent": item.value}
            for item in outputs
        ]
        stack = device.configuration.get("layer_stack", []) if device else []
        values_correct = bool(
            len(points) == expected["point_count"]
            and canonical_digest(points) == expected["points_sha256"]
        )
        conditions_correct = bool(outputs and all(
            item.property == "external_quantum_efficiency"
            and item.unit == "%"
            and item.conditions.get("wavelength_unit") == "nm"
            and item.conditions.get("series_id") == expected["label"]
            and item.conditions.get("scientific_type") == "reported_measurement"
            for item in outputs
        ))
        architecture_correct = bool(device and [layer["role"] for layer in stack] == [
            "transparent_electrode", "htl", "absorber", "buffer", "electrode",
        ])
        source_tracked = bool(outputs and all(
            item.evidence
            and item.evidence[0].page is None
            and item.evidence[0].original_source_type == "official_source_data_workbook"
            and item.evidence[0].table_id
            and f"series={expected['label']}" in (item.evidence[0].locator or "")
            and item.raw_value in (item.evidence[0].text_snippet or "")
            for item in outputs
        ))
        assertions.append({
            "variant": variant,
            "values_correct": values_correct,
            "conditions_correct": conditions_correct,
            "architecture_correct": architecture_correct,
            "source_tracked": source_tracked,
            "passed": all((values_correct, conditions_correct, architecture_correct, source_tracked)),
        })
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions),
        "assertions": assertions,
        "devices": len(archive.devices),
        "experiments": len(archive.experiments),
        "outputs": sum(len(item.outputs) for item in archive.experiments),
        "analytics_rows": len(analytics),
        "scientific_safety": {
            "all_points_device_linked": all(row.device_id for row in analytics),
            "wavelength_and_series_preserved": all(
                row.conditions.get("wavelength") is not None
                and row.conditions.get("series_id")
                for row in analytics
            ),
            "percent_values_not_fractionalized": max(row.value for row in analytics) > 80,
            "quarantine_count": _quarantine_count(archive),
        },
    }


def score_stab_c(archive, gold: dict) -> dict:
    devices = _variant_devices(archive)
    experiments = _experiments_by_variant(archive)
    assertions = []
    for expected in gold["variants"]:
        variant = expected["variant"]
        device = devices.get(variant)
        experiment = experiments.get(variant)
        outputs = {item.property: item for item in experiment.outputs} if experiment else {}
        t80 = outputs.get("t80")
        values_correct = bool(
            t80
            and t80.value == expected["t80"]
            and t80.unit == "h"
            and t80.qualifier == expected["qualifier"]
            and (
                "retained_efficiency" not in expected
                or outputs.get("retained_efficiency") is not None
                and outputs["retained_efficiency"].value == expected["retained_efficiency"]
                and outputs["retained_efficiency"].conditions.get("aging_time") == expected["aging_time_h"]
            )
        )
        conditions_correct = bool(t80 and all(
            t80.conditions.get(key) == value
            for key, value in {
                "aging_protocol": gold["protocol"]["aging_protocol"],
                "temperature": gold["protocol"]["temperature"],
                "atmosphere": gold["protocol"]["atmosphere"],
                "encapsulation": expected["encapsulation"],
                "absorber": expected["absorber"],
            }.items()
        ))
        stack = device.configuration.get("layer_stack", []) if device else []
        architecture_correct = bool(
            device
            and [layer["sequence_index"] for layer in stack] == list(range(len(stack)))
            and "absorber" in [layer["role"] for layer in stack]
            and ((expected["encapsulation"] == "none") == ("encapsulation" not in [layer["role"] for layer in stack]))
        )
        source_tracked = bool(
            t80 and t80.evidence and t80.evidence[0].page == 9
            and t80.evidence[0].source_type.value == "supplementary"
            and t80.raw_value in (t80.evidence[0].text_snippet or "")
        )
        assertions.append({
            "variant": variant,
            "values_correct": values_correct,
            "conditions_correct": conditions_correct,
            "architecture_correct": architecture_correct,
            "source_tracked": source_tracked,
            "passed": all((values_correct, conditions_correct, architecture_correct, source_tracked)),
        })
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions),
        "assertions": assertions,
        "devices": len(archive.devices),
        "experiments": len(archive.experiments),
        "outputs": sum(len(item.outputs) for item in archive.experiments),
        "analytics_rows": len(analytics),
        "scientific_safety": {
            "initial_reference_and_aged_state_preserved": any(
                output.property == "retained_efficiency"
                and output.conditions.get("state_reference") == "initial PCE"
                and output.conditions.get("measurement_state") == "aged"
                for experiment in archive.experiments for output in experiment.outputs
            ),
            "lower_bound_not_promoted_to_exact": any(
                output.property == "t80" and output.qualifier == "lower_bound"
                for experiment in archive.experiments for output in experiment.outputs
            ),
            "all_outputs_device_linked": all(row.device_id for row in analytics),
            "quarantine_count": _quarantine_count(archive),
        },
    }


def score_stack_d(archive, gold: dict) -> dict:
    devices = _variant_devices(archive)
    experiments = _experiments_by_variant(archive)
    process_by_device = {
        output: process for process in archive.processes for output in process.outputs
        if output in {device.device_id for device in archive.devices}
    }
    assertions = []
    properties = {
        "open_circuit_voltage", "short_circuit_current_density", "fill_factor", "power_conversion_efficiency",
    }
    for expected in gold["variants"]:
        variant = expected["variant"]
        device = devices.get(variant)
        experiment = experiments.get(variant)
        process = process_by_device.get(device.device_id) if device else None
        outputs = {item.property: item for item in experiment.outputs} if experiment else {}
        parameters = {item.property: item for item in process.parameters} if process else {}
        values_correct = bool(outputs and all(outputs[name].value == expected[name] for name in properties))
        conditions_correct = bool(outputs and all(
            item.conditions.get("illumination_spectrum") == "AM1.5G"
            and item.conditions.get("irradiance") == 100.0
            and item.conditions.get("active_area") == 9.0
            for item in outputs.values()
        ))
        stack = device.configuration.get("layer_stack", []) if device else []
        architecture_correct = bool(device and [layer["role"] for layer in stack] == gold["layer_roles"])
        process_correct = bool(
            process
            and parameters.get("film_thickness") is not None
            and parameters["film_thickness"].value == expected["pc70bm_thickness_nm"]
            and (
                expected["dopant_wt_percent"] is None and "solution_concentration" not in parameters
                or expected["dopant_wt_percent"] is not None
                and parameters.get("solution_concentration") is not None
                and parameters["solution_concentration"].value == expected["dopant_wt_percent"]
            )
        )
        source_tracked = bool(outputs and all(
            item.evidence and item.evidence[0].page == 3
            and item.evidence[0].table_id
            and item.raw_value in (item.evidence[0].text_snippet or "")
            for item in outputs.values()
        ))
        assertions.append({
            "variant": variant,
            "values_correct": values_correct,
            "conditions_correct": conditions_correct,
            "architecture_correct": architecture_correct,
            "process_correct": process_correct,
            "source_tracked": source_tracked,
            "passed": all((values_correct, conditions_correct, architecture_correct, process_correct, source_tracked)),
        })
    analytics = project_archives([archive])
    return {
        "case_id": gold["case_id"],
        "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions),
        "assertions": assertions,
        "devices": len(archive.devices),
        "processes": len(archive.processes),
        "experiments": len(archive.experiments),
        "outputs": sum(len(item.outputs) for item in archive.experiments),
        "analytics_rows": len(analytics),
        "scientific_safety": {
            "variant_identity_preserved": len(devices) == len(gold["variants"]),
            "stack_order_preserved": all(
                [layer["sequence_index"] for layer in device.configuration["layer_stack"]] == list(range(6))
                for device in archive.devices
            ),
            "property_identity_preserved": all(set(item.property for item in experiment.outputs) == properties for experiment in archive.experiments),
            "all_outputs_device_linked": all(row.device_id for row in analytics),
            "quarantine_count": _quarantine_count(archive),
        },
    }
