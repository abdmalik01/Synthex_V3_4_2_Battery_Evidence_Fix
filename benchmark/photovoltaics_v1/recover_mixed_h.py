"""Deterministic multimodal recovery for PV-MIXED-H."""

from __future__ import annotations

import pymupdf

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftDevice,
    DraftDeviceLayer,
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)

from .case_common import load_locked, measurement, normalize_text, table_evidence, text_evidence


def recover_mixed_h():
    source_path, gold, lock = load_locked("mixed_h_source_lock.json")
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("PV-MIXED-H page count differs from source lock")
        performance_text = normalize_text(document[4].get_text())
        table_text = normalize_text(document[5].get_text())
        fabrication_text = normalize_text(document[6].get_text())
        methods_text = normalize_text(document[7].get_text())
    if not all(term in performance_text for term in ("23.4%", "32.19", "0.877", "31.0", "30.2", "22.94%", "1080 h")):
        raise ValueError("PV-MIXED-H performance context changed")
    if not all(term in table_text for term in ("Table 1", "NBG", "Reverse", "82.9", "23.4")):
        raise ValueError("PV-MIXED-H Table 1 changed")
    if not all(term in fabrication_text for term in ("ITO glass", "PEDOT:PSS", "25 nm of C60", "SnO2", "90 nm Ag", "1 mg mL")):
        raise ValueError("PV-MIXED-H fabrication context changed")
    if not all(term in methods_text for term in ("AM 1.5 G", "100 mW cm", "300–1100 nm", "85 °C")):
        raise ValueError("PV-MIXED-H characterization context changed")

    stack_evidence = text_evidence(
        7,
        "perovskite solar cells with an inverted p-i-n structure were assembled",
        section="Device fabrication for NBG mixed Sn-Pb PSCs",
    )
    process_evidence = text_evidence(
        7,
        "0 mg mL-1, 1 mg mL-1, and 2 mg mL-1 of additive o-CB were dissolved into the precursor mixture",
        section="Precursor solution preparation",
    )
    characterization_evidence = text_evidence(
        8,
        "under AM 1.5 G illumination at 100 mW cm-2 with a solar simulator",
        section="PSC characterization",
    )
    layer_specs = [
        ("ito", "indium tin oxide", "ITO", "transparent_electrode"),
        ("pedot_pss", "PEDOT:PSS", None, "htl"),
        ("sn_pb_perovskite", "mixed Sn-Pb perovskite", None, "absorber"),
        ("c60", "C60", "C60", "etl"),
        ("sno2", "tin oxide", "SnO2", "buffer"),
        ("ag", "silver electrode", "Ag", "electrode"),
    ]
    materials = [
        DraftMaterial(
            local_id=local_id, name=name, formula=formula, tags=[role],
            ownership="focal_work", evidence=[stack_evidence],
        )
        for local_id, name, formula, role in layer_specs
    ]
    devices = []
    processes = []
    experiments = []
    variants = {item["variant"]: item for item in gold["variants"]}
    for variant, spec in variants.items():
        device_ref = f"device_{variant}"
        devices.append(DraftDevice(
            local_id=device_ref,
            name=f"NBG mixed Sn-Pb PSC - {variant}",
            device_type="solar_cell",
            layer_stack=[
                DraftDeviceLayer(
                    sequence_index=index, role=role, material_ref=local_id,
                    evidence=[stack_evidence],
                )
                for index, (local_id, _, _, role) in enumerate(layer_specs)
            ],
            configuration={
                "architecture": gold["architecture"],
                "variant": variant,
                "o_cb_concentration_mg_ml": spec["o_cb_concentration_mg_ml"],
            },
            tags=["inverted", "mixed_sn_pb", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[stack_evidence, process_evidence],
        ))
        raw_concentration = f"{spec['o_cb_concentration_mg_ml']:g} mg mL-1"
        processes.append(DraftProcess(
            local_id=f"fabricate_{variant}",
            name=f"Fabricate {variant} NBG mixed Sn-Pb PSC",
            family="inverted_perovskite_solar_cell_fabrication",
            input_material_refs=[item[0] for item in layer_specs],
            output_device_refs=[device_ref],
            parameters=[measurement(
                "solution_concentration", raw_concentration,
                spec["o_cb_concentration_mg_ml"], "mg/ml", process_evidence,
                scientific_type="reported_process_parameter",
                conditions={"process_step": "o-CB addition to perovskite precursor", "additive": "ortho-carborane"},
            )],
            atmosphere="N2-filled glove box for perovskite coating",
            equipment="spin coater, thermal evaporator, ALD system",
            ownership="focal_work",
            evidence=[stack_evidence, process_evidence],
        ))

    table_snippet = "NBG Reverse 32.19 0.877 82.9 23.4"
    performance_evidence = table_evidence(
        page=6, table="Table 1. PV parameters of narrow-bandgap, wide-bandgap PSCs and all-perovskite tandem solar cells",
        row="NBG Reverse", column="Jsc,Voc,FF,PCE", snippet=table_snippet,
        source_sha256=lock["source_sha256"],
    )
    common_performance_conditions = {
        "illumination_spectrum": "AM1.5G", "irradiance": 100.0,
        "irradiance_unit": "mW/cm2", "scan_direction": "reverse",
        "measurement_modality": "performance",
    }
    performance_outputs = [
        measurement("short_circuit_current_density", "32.19", 32.19, "mA/cm2", performance_evidence, scientific_type="reported_measurement", conditions=common_performance_conditions),
        measurement("open_circuit_voltage", "0.877", 0.877, "V", performance_evidence, scientific_type="reported_measurement", conditions=common_performance_conditions),
        measurement("fill_factor", "82.9", 82.9, "%", performance_evidence, scientific_type="reported_measurement", conditions=common_performance_conditions),
        measurement("power_conversion_efficiency", "23.4", 23.4, "%", performance_evidence, scientific_type="reported_measurement", conditions=common_performance_conditions),
    ]
    experiments.append(DraftExperiment(
        local_id="performance_o_cb", experiment_type="current_voltage_photovoltaic_performance",
        device_refs=["device_o_cb"], outputs=performance_outputs,
        protocol="reverse J-V scan under AM1.5G at 100 mW/cm2",
        ownership="focal_work", evidence=[performance_evidence, characterization_evidence],
    ))

    spectral_snippet = "The integrated current density of 31.0 mA cm-2 and 30.2 mA cm-2 agreed well with the values from J-V measurements."
    spectral_evidence = text_evidence(5, spectral_snippet, section="Solar cell efficiency and stability")
    for variant, raw, value in (("o_cb", "31.0", 31.0), ("pristine", "30.2", 30.2)):
        experiments.append(DraftExperiment(
            local_id=f"spectral_{variant}", experiment_type="external_quantum_efficiency_spectral_summary",
            device_refs=[f"device_{variant}"],
            outputs=[measurement(
                "eqe_integrated_current_density", raw, value, "mA/cm2", spectral_evidence,
                scientific_type="reported_derived_metric",
                conditions={
                    "spectral_range": "300-1100 nm", "measurement_modality": "spectral_summary",
                    "source_series": "EQE spectrum", "no_digitized_points": True,
                },
            )],
            protocol="EQE spectrum acquired over 300-1100 nm; only the author-reported integral is recovered",
            ownership="focal_work", evidence=[spectral_evidence, characterization_evidence],
        ))

    stabilized_snippet = "resulted in a stabilized PCE of 22.94% and 20.18% without decay for 300 s, respectively"
    stabilized_evidence = text_evidence(5, stabilized_snippet, section="Solar cell efficiency and stability")
    experiments.append(DraftExperiment(
        local_id="stabilized_o_cb", experiment_type="maximum_power_point_stabilized_output",
        device_refs=["device_o_cb"],
        outputs=[measurement(
            "stabilized_power_conversion_efficiency", "22.94", 22.94, "%", stabilized_evidence,
            scientific_type="reported_measurement",
            conditions={
                "illumination_spectrum": "AM1.5G", "irradiance": 100.0,
                "irradiance_unit": "mW/cm2", "measurement_mode": "maximum power point",
                "measurement_duration": 300.0, "measurement_duration_unit": "s",
                "measurement_modality": "stabilized_output",
            },
        )],
        protocol="stabilized power output at maximum power point for 300 s",
        ownership="focal_work", evidence=[stabilized_evidence, characterization_evidence],
    ))

    stability_snippet = "The o-CB treated devices retained 80% of the original PCE after 1080 h, while the pristine devices maintained only 40% of the initial PCE after ~200 h"
    stability_evidence = text_evidence(5, stability_snippet, section="Solar cell efficiency and stability")
    for variant, raw, value, hours, qualifier in (
        ("o_cb", "80", 80.0, 1080.0, "exact"),
        ("pristine", "40", 40.0, 200.0, "approx"),
    ):
        experiments.append(DraftExperiment(
            local_id=f"thermal_stability_{variant}", experiment_type="thermal_stability_retention",
            device_refs=[f"device_{variant}"],
            outputs=[measurement(
                "retained_efficiency", raw, value, "%", stability_evidence,
                scientific_type="reported_measurement", qualifier=qualifier,
                conditions={
                    "aging_time": hours, "aging_time_unit": "h", "temperature": 85.0,
                    "temperature_unit": "C", "atmosphere": "glove box",
                    "encapsulation": "unencapsulated", "aging_protocol": "thermal stability",
                    "state_reference": "initial PCE", "measurement_state": "aged",
                    "measurement_modality": "thermal_stability",
                },
            )],
            protocol="unencapsulated device thermal aging at 85 C in a glove box",
            ownership="focal_work", evidence=[stability_evidence],
        ))

    source = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source["title"], doi=source["doi"], url=source["url"],
            year=source["year"], authors=source["authors"],
        ),
        materials=materials, devices=devices, processes=processes, experiments=experiments,
        domain_values={
            "case_id": gold["case_id"], "provider_invoked": False,
            "source_checksum": lock["source_sha256"],
            "modalities": ["performance", "spectral_summary", "stabilized_output", "thermal_stability"],
            "spectral_policy": "author_reported_integral_only_no_curve_digitization_or_interpolation",
        },
    )
    return assemble_archive(draft, domain="photovoltaics", model="deterministic_multimodal_recovery")
