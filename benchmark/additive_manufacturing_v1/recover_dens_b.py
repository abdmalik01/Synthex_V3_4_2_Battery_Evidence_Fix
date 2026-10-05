"""Deterministic table recovery for AM-DENS-B."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)

from .benchmark_common import load_locked, measurement, table_evidence, text_evidence


_ROW = re.compile(
    r"^([1-9])\s*\n(190|260|330)\s*\n(1000|1350|1700)\s*\n"
    r"(0\.05|0\.1|0\.15)\s*\n(0|67|90)\s*$",
    re.MULTILINE,
)


def _numbers_after(label: str, text: str) -> list[float]:
    match = re.search(label + r"\s*\n((?:\d+(?:\.\d+)?\s*\n?){9})", text, re.IGNORECASE)
    if not match:
        raise ValueError(f"AM-DENS-B table row missing: {label}")
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", match.group(1))]


def recover_dens_b():
    source, gold, lock = load_locked("dens_b_source_lock.json")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-DENS-B page count differs from lock")
        process_text = document[3].get_text().replace("ﬁ", "fi")
        density_text = document[7].get_text().replace("ﬁ", "fi")
        defect_text = document[12].get_text().replace("ﬁ", "fi")

    process_rows = [
        {
            "sample": match.group(1),
            "laser_power_w": float(match.group(2)),
            "scan_speed_mm_s": float(match.group(3)),
            "hatch_spacing_mm": float(match.group(4)),
            "rotation_angle_deg": float(match.group(5)),
            "process_snippet": match.group(0).strip(),
        }
        for match in _ROW.finditer(process_text)
    ]
    energies = _numbers_after(r"Energy\s+density\s+J/mm3", density_text)
    densities = _numbers_after(r"Relative\s+density%", density_text)
    if len(process_rows) != 9 or len(energies) != 9 or len(densities) != 9:
        raise ValueError("AM-DENS-B tables did not yield nine unambiguous rows")
    rows = []
    for row, energy, density in zip(process_rows, energies, densities, strict=True):
        rows.append({
            **{key: row[key] for key in (
                "sample", "laser_power_w", "scan_speed_mm_s",
                "hatch_spacing_mm", "rotation_angle_deg",
            )},
            "volumetric_energy_density_j_mm3": energy,
            "relative_density_pct": density,
        })
    if rows != gold["rows"]:
        raise ValueError("AM-DENS-B recovered values differ from frozen gold")
    for phrase in ("lapping defects", "unfused powder", "unfused holes", "spherical"):
        if phrase not in defect_text:
            raise ValueError(f"AM-DENS-B defect statement changed: {phrase}")

    feedstock_ev = text_evidence(
        3, "2.1. Material",
        "gas-atomized 316 L stainless steel powder with an approximately spherical shape",
    )
    machine_ev = text_evidence(3, "2.2. Experimental Method", "EOSM290")
    gas_ev = text_evidence(3, "2.2. Experimental Method", "nitrogen")
    layer_ev = text_evidence(4, "2.2. Experimental Method", "40 µm")
    materials = [DraftMaterial(
        local_id="feedstock", name="gas-atomized 316L stainless steel powder",
        formula="316L", morphology={
            "shape": "approximately spherical", "particle_size_d10_um": 25.97,
            "particle_size_d50_um": 40.48, "particle_size_d90_um": 63.34,
        }, tags=["am_feedstock", "powder"], ownership="focal_work",
        evidence=[feedstock_ev],
    )]
    processes = []
    experiments = []
    recovered = []
    for source_row, expected in zip(process_rows, rows, strict=True):
        sample = expected["sample"]
        specimen = f"specimen_{sample}"
        process_ev = table_evidence(4, "Table 2", sample, "process coordinates", source_row["process_snippet"])
        density_snippet = f'{expected["relative_density_pct"]:.2f}'
        density_ev = table_evidence(8, "Table 4", sample, "Relative density/%", density_snippet)
        energy_raw = f'{expected["volumetric_energy_density_j_mm3"]:.2f}'
        energy_ev = table_evidence(8, "Table 4", sample, "Energy density/J/mm3", energy_raw)
        materials.append(DraftMaterial(
            local_id=specimen, name=f"sample {sample} LPBF 316L specimen", formula="316L",
            tags=["am_part", f"source_sample:{sample}"], ownership="focal_work",
            evidence=[process_ev],
        ))
        parameters = [
            measurement("laser_power", str(int(expected["laser_power_w"])), expected["laser_power_w"], "W", process_ev, scientific_type="reported_process_parameter"),
            measurement("scan_speed", str(int(expected["scan_speed_mm_s"])), expected["scan_speed_mm_s"], "mm/s", process_ev, scientific_type="reported_process_parameter"),
            measurement("hatch_spacing", str(expected["hatch_spacing_mm"]), expected["hatch_spacing_mm"], "mm", process_ev, scientific_type="reported_process_parameter"),
            measurement("rotation_angle", str(int(expected["rotation_angle_deg"])), expected["rotation_angle_deg"], "°", process_ev, scientific_type="reported_process_parameter"),
            measurement("layer_thickness", "40", 40.0, "µm", layer_ev, scientific_type="reported_process_parameter"),
            measurement("volumetric_energy_density", energy_raw, expected["volumetric_energy_density_j_mm3"], "J/mm3", energy_ev, scientific_type="reported_derived_metric"),
            measurement("machine_model", "EOSM290", "EOSM290", None, machine_ev, scientific_type="reported_process_parameter"),
            measurement("shielding_gas", "nitrogen", "nitrogen", None, gas_ev, scientific_type="reported_process_parameter"),
        ]
        processes.append(DraftProcess(
            local_id=f"build_{sample}", name=f"LPBF build sample {sample}",
            family="laser_powder_bed_fusion", input_material_refs=["feedstock"],
            output_material_refs=[specimen], parameters=parameters,
            atmosphere="nitrogen", equipment="EOSM290", ownership="focal_work",
            evidence=[process_ev],
        ))
        output = measurement(
            "relative_density", density_snippet, expected["relative_density_pct"], "%",
            density_ev, scientific_type="reported_measurement",
            conditions={"reported_term": "Relative density", "method": "Archimedes"},
        )
        output.method = "Archimedes method"
        experiments.append(DraftExperiment(
            local_id=f"density_{sample}", experiment_type="relative_density_measurement",
            material_refs=[specimen], target="densification", outputs=[output],
            protocol="Archimedes method", ownership="focal_work", evidence=[density_ev],
        ))
        recovered.append(expected)

    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], url=source_info["url"],
            year=source_info["year"], authors=source_info["authors"],
        ),
        materials=materials,
        processes=processes,
        experiments=experiments,
        domain_values={
            "case_id": gold["case_id"], "provider_invoked": False,
            "source_checksum": lock["source_sha256"],
            "defect_identity": gold["defect_identity"],
            "scientific_boundaries": gold["scientific_boundaries"],
        },
    )
    return assemble_archive(draft, domain="additive_manufacturing", model="deterministic_table_recovery"), recovered
