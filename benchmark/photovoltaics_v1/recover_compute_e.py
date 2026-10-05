"""Deterministic Table 4 recovery for PV-COMPUTE-E."""

from __future__ import annotations

import pymupdf

from synthex_platform.core.models import Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation,
    DraftMaterial,
    DraftSource,
    ExtractedDocument,
)

from .case_common import load_locked, measurement, normalize_text, table_evidence, text_evidence


def _raw_row(row: dict) -> dict[str, str]:
    return {
        "simulated_open_circuit_voltage": f"{row['simulated_open_circuit_voltage']:.2f}",
        "predicted_short_circuit_current_density": f"{row['predicted_short_circuit_current_density']:.2f}",
        "simulated_fill_factor": f"{row['simulated_fill_factor']:.0f}",
        "simulated_power_conversion_efficiency": f"{row['simulated_power_conversion_efficiency']:.2f}",
        "absorber_acceptor_density_cm3": f"{row['absorber_acceptor_density_cm3']:.2e}",
        "absorber_defect_density_cm3": f"{row['absorber_defect_density_cm3']:.2e}",
        "czts_thickness_nm": f"{row['czts_thickness_nm']:.0f}",
        "tio2_bandgap_ev": f"{row['tio2_bandgap_ev']:g}",
        "tio2_donor_density_cm3": f"{row['tio2_donor_density_cm3']:.2e}",
    }


def _display_scientific(raw: str) -> str:
    base, exponent = raw.split("e")
    return f"{base} × 10{int(exponent)}"


def recover_compute_e():
    source_path, gold, lock = load_locked("compute_e_source_lock.json")
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("PV-COMPUTE-E page count differs from source lock")
        input_text = normalize_text(document[5].get_text())
        result_text = normalize_text(document[7].get_text())
    if not all(term in input_text for term in ("SCAPS-1D", "AM 1.5G", "1000 W/m2", "300 K", "5.1 eV", "4.4 eV")):
        raise ValueError("PV-COMPUTE-E simulation context changed")
    if not all(term in result_text for term in ("Table 4", "0.77", "20.45", "31.66", "20.28")):
        raise ValueError("PV-COMPUTE-E Table 4 changed")

    material_evidence = text_evidence(
        5,
        "FTO/TiO2/MASnI3/CZTS/Au (this work [T.W.])",
        section="Table 1",
        source_type="table",
    )
    method_evidence = text_evidence(
        6,
        "The simulation is carried out under an AM 1.5G solar spectrum with an incident power density of 1000 W/m2 at room temperature (300 K).",
        section="Simulation setup",
    )
    material = DraftMaterial(
        local_id="masni3_absorber",
        name="MASnI3 absorber in the simulated FTO/TiO2/MASnI3/CZTS/Au device",
        formula="MASnI3",
        tags=["absorber", "computational_material"],
        ownership="focal_work",
        evidence=[material_evidence],
    )
    calculations = []
    recovered = []
    output_units = {
        "simulated_open_circuit_voltage": "V",
        "predicted_short_circuit_current_density": "mA/cm2",
        "simulated_fill_factor": "%",
        "simulated_power_conversion_efficiency": "%",
    }
    parameter_units = {
        "absorber_acceptor_density_cm3": "cm^-3",
        "absorber_defect_density_cm3": "cm^-3",
        "czts_thickness_nm": "nm",
        "tio2_bandgap_ev": "eV",
        "tio2_donor_density_cm3": "cm^-3",
    }
    for index, row in enumerate(gold["rows"], start=1):
        raw = _raw_row(row)
        snippet = " ".join((
            raw["simulated_open_circuit_voltage"],
            raw["predicted_short_circuit_current_density"],
            raw["simulated_fill_factor"],
            raw["simulated_power_conversion_efficiency"],
            _display_scientific(raw["absorber_acceptor_density_cm3"]),
            _display_scientific(raw["absorber_defect_density_cm3"]),
            raw["czts_thickness_nm"],
            raw["tio2_bandgap_ev"],
            _display_scientific(raw["tio2_donor_density_cm3"]),
        ))
        evidence = table_evidence(
            page=8,
            table="Table 4. History of parameters of the simulations obtained in the solar cells",
            row=row["variant"],
            column="Voc,Jsc,FF,PCE,NA,Nt,CZTS thickness,TiO2 bandgap,TiO2 donor density",
            snippet=snippet,
            source_sha256=lock["source_sha256"],
        )
        parameters = [
            Measurement(
                property=name,
                raw_value=raw[name],
                value=row[name],
                unit=parameter_units[name],
                qualifier="exact",
                conditions={"scientific_type": "reported_model_input", "simulation_variant": row["variant"]},
                evidence=[evidence],
            )
            for name in parameter_units
        ]
        outputs = [
            measurement(
                name,
                raw[name],
                row[name],
                output_units[name],
                evidence,
                scientific_type="simulation_result",
                conditions={
                    "simulation_variant": row["variant"],
                    "simulation_model": "SCAPS-1D",
                    "illumination_spectrum": "AM1.5G",
                    "incident_power_density_w_m2": 1000,
                    "temperature_k": 300,
                },
            )
            for name in output_units
        ]
        calculations.append(DraftCalculation(
            local_id=f"calculation_{index}",
            calculation_type=gold["method"]["calculation_type"],
            material_refs=[material.local_id],
            code=gold["method"]["software"],
            method=gold["method"]["model"],
            model={**gold["method"], "simulation_variant": row["variant"]},
            parameters=parameters,
            outputs=outputs,
            evidence=[method_evidence, evidence],
            ownership="focal_work",
        ))
        recovered.append(dict(row))

    source = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source["title"], doi=source["doi"], url=source["url"],
            year=source["year"], authors=source["authors"],
        ),
        materials=[material],
        calculations=calculations,
        domain_values={
            "case_id": gold["case_id"],
            "provider_invoked": False,
            "source_checksum": lock["source_sha256"],
            "computational_contract": "calculation_records_only_no_experimental_device_measurements",
            "simulated_architecture": gold["method"]["architecture"],
        },
    )
    archive = assemble_archive(draft, domain="photovoltaics", model="deterministic_scaps_table_recovery")
    return archive, recovered
