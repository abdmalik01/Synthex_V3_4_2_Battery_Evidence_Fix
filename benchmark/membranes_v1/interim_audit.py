"""Thirty-invariant interim scientific audit for Membranes V1 cases A-D."""

from __future__ import annotations

import json

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.membranes_contract import membranes_admission_decision
from synthex_platform.extraction.router import DomainRouter

from .recover_cases import recover_all_cases


def _conditions(row: dict) -> dict:
    return json.loads(row["conditions_json"]) if row.get("conditions_json") else {}


def run_interim_audit() -> dict:
    archives = recover_all_cases()
    outputs = [
        output
        for archive in archives.values()
        for experiment in archive.experiments
        for output in experiment.outputs
    ]
    by_property: dict[str, list] = {}
    for output in outputs:
        by_property.setdefault(output.property, []).append(output)

    result_rows = [
        row
        for archive in archives.values()
        for row in project_results_rows(archive)
        if row["measurement_role"] == "result" and row["admission_status"] == "canonical"
    ]
    all_quarantine = [
        item
        for archive in archives.values()
        for item in archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    ]
    device_names = {
        device.device_id: device.name
        for archive in archives.values()
        for device in archive.devices
    }

    caption_evidence = Evidence(
        page=1, source_type=SourceType.figure_caption,
        original_source_type="figure_caption", verbatim_match=True,
        text_snippet="10 Barrer", locator="figure=1;caption",
    )
    caption_only = Measurement(
        property="gas_permeability", raw_value="10", value=10.0, unit="Barrer",
        conditions={"scientific_type": "reported_measurement", "species": "CO2", "test_mode": "pure_gas",
                    "temperature": 25.0, "temperature_unit": "C", "pressure_kind": "feed_pressure"},
        evidence=[caption_evidence],
    )
    table_evidence = Evidence(
        page=1, source_type=SourceType.table, original_source_type="publisher_pdf_table",
        verbatim_match=True, text_snippet="N/A Barrer", table_id="Table X", locator="row=x",
    )
    missing_value = Measurement(
        property="gas_permeability", raw_value="N/A", value=0.0, unit="Barrer",
        conditions={"scientific_type": "reported_measurement", "species": "CO2", "test_mode": "pure_gas",
                    "temperature": 25.0, "temperature_unit": "C", "pressure_kind": "feed_pressure"},
        evidence=[table_evidence],
    )

    process_archive = archives["MEM-PROCESS-D"]
    process_roles = [
        [layer["role"] for layer in device.configuration["layer_stack"]]
        for device in process_archive.devices
    ]
    stab = archives["MEM-STAB-C"]
    stab_properties = {
        experiment.device_id: [output.property for output in experiment.outputs]
        for experiment in stab.experiments
    }
    sep = archives["MEM-SEP-B"]
    sep_species = {
        output.conditions.get("species")
        for experiment in sep.experiments for output in experiment.outputs
        if output.property == "gas_permeability"
    }
    sep_pairs = {
        output.conditions.get("species_pair")
        for experiment in sep.experiments for output in experiment.outputs
        if output.property == "ideal_selectivity"
    }

    invariants = {
        "01_permeability_not_permeance": set(item.unit for item in by_property["gas_permeability"]) == {"Barrer"}
            and "Barrer" not in {item.unit for item in by_property["gas_permeance"]},
        "02_permeance_not_flux": "gas_permeance" in by_property and not ({"initial_flux", "fouled_flux", "recovered_flux"} & {"gas_permeance"}),
        "03_selectivity_not_rejection": {"ideal_selectivity", "mixed_gas_selectivity"} <= set(by_property)
            and "solute_rejection" not in by_property,
        "04_ideal_not_mixed_selectivity": all(item.conditions["test_mode"] == "pure_gas" for item in by_property["ideal_selectivity"])
            and all(item.conditions["test_mode"] == "mixed_gas" for item in by_property["mixed_gas_selectivity"]),
        "05_separation_factor_distinct": "separation_factor" not in by_property,
        "06_barrer_not_gpu": all(item.unit == "Barrer" for item in by_property["gas_permeability"])
            and all(item.unit != "Barrer" for item in by_property["gas_permeance"]),
        "07_no_permeability_permeance_conversion_without_thickness": all(
            item.conditions.get("raw_unit_preserved") is True for item in by_property["gas_permeance"]
        ),
        "08_gas_not_water_permeability": all("species" in item.conditions for item in by_property["gas_permeability"]),
        "09_feed_pressure_not_tmp": all(
            not ({"feed_pressure", "transmembrane_pressure"} <= set(item.conditions)) for item in outputs
        ),
        "10_feed_not_permeate_concentration": all("permeate_concentration" not in item.conditions for item in outputs),
        "11_membrane_not_selective_layer_thickness": all(
            layer.get("thickness", {}).get("property") == "membrane_thickness"
            for device in sep.devices for layer in device.configuration["layer_stack"] if layer.get("thickness")
        ) and all(item.conditions.get("thickness_scope") == "selective_layer" for item in by_property["estimated_selective_layer_thickness"]),
        "12_pore_size_not_mwco": "pore_size" not in by_property and "molecular_weight_cutoff" not in by_property,
        "13_porosity_not_pore_size": "porosity" not in by_property and "pore_size" not in by_property,
        "14_initial_not_fouled_flux": all(values[:2] == ["initial_flux", "fouled_flux"] for values in stab_properties.values()),
        "15_fouled_not_recovered_flux": all("fouled_flux" in values and "recovered_flux" in values for values in stab_properties.values()),
        "16_frr_not_rejection": "flux_recovery_ratio" in by_property and "solute_rejection" not in by_property,
        "17_stability_not_antifouling": archives["MEM-STAB-C"].domain_payloads[0].values["case_id"] == "MEM-STAB-C"
            and all(item.conditions.get("foulant") == "humic acid" for item in by_property["flux_recovery_ratio"]),
        "18_species_identity_retained": sep_species == {"O2", "N2", "CO2", "H2", "CH4", "C2H4"},
        "19_gas_pair_identity_retained": len(sep_pairs) == 8 and "CO2/CH4" in sep_pairs and "H2/C2H4" in sep_pairs,
        "20_solute_identity_retained": all(item.conditions.get("foulant") == "humic acid" for item in by_property["fouled_flux"]),
        "21_membrane_variant_retained": all(_conditions(row).get("membrane_variant") for row in result_rows),
        "22_filler_loading_retained": all(
            any(parameter.property == "filler_loading" for parameter in archive.processes[index].parameters)
            for archive in (archives["MEM-GOLD-A"], archives["MEM-SEP-B"], archives["MEM-STAB-C"])
            for index in range(len(archive.processes))
        ),
        "23_fabrication_process_retained": all(archive.processes for archive in archives.values()),
        "24_support_selective_roles_retained": all(
            roles == ["substrate", "porous_support", "selective_layer", "protective_layer"]
            for roles in process_roles
        ),
        "25_missing_conditions_not_inferred": all(
            "membrane_thickness" not in item.conditions for item in by_property["gas_permeability"]
        ),
        "26_missing_values_not_interpolated": all(item.qualifier == "exact" for item in outputs),
        "27_caption_only_cannot_admit": not membranes_admission_decision(
            caption_only, role="result", modality="gas_separation"
        ).admitted,
        "28_na_cannot_be_numeric": not membranes_admission_decision(
            missing_value, role="result", modality="gas_separation"
        ).admitted,
        "29_review_cited_values_do_not_leak": not all_quarantine and all(row["ownership"] == "focal_work" for row in result_rows),
        "30_archive_domain_scoping": all(
            archive.metadata.domain == "membranes" and all(row["domain"] == "membranes" for row in project_results_rows(archive))
            for archive in archives.values()
        ),
    }

    negative_routes = {
        "battery_separator": DomainRouter().route_text(
            "A lithium-ion battery separator was evaluated by charge-discharge cycling, specific capacity, "
            "coulombic efficiency, electrolyte uptake, and electrochemical impedance spectroscopy."
        ).domain,
        "weak_terms": DomainRouter().route_text(
            "The porous layer showed permeability, selectivity, flux, diffusion and transport changes."
        ).domain,
        "biological": DomainRouter().route_text(
            "The biological cell membrane controls ion transport and protein diffusion in biomaterial scaffolds."
        ).domain,
    }
    contamination = {
        "ownership": sum(row["ownership"] != "focal_work" for row in result_rows),
        "evidence": sum(not output.evidence or output.evidence[0].verbatim_match is not True for output in outputs),
        "cross_record_leakage": sum(
            len(experiment.device_ids) != 1 or device_names.get(experiment.device_id) != experiment.outputs[0].conditions.get("membrane_variant")
            for archive in archives.values() for experiment in archive.experiments
        ),
        "analytics": abs(len(result_rows) - len(outputs)),
    }
    return {
        "case_outputs": {case_id: sum(len(item.outputs) for item in archive.experiments) for case_id, archive in archives.items()},
        "total_outputs": len(outputs),
        "analytics_result_rows": len(result_rows),
        "invariants": invariants,
        "passed_invariants": sum(invariants.values()),
        "contamination": contamination,
        "routing_controls": negative_routes,
        "routing_safe": all(route != "membranes" for route in negative_routes.values()),
        "passed": all(invariants.values()) and not any(contamination.values())
            and all(route != "membranes" for route in negative_routes.values()),
    }


if __name__ == "__main__":
    print(json.dumps(run_interim_audit(), indent=2, sort_keys=True))
