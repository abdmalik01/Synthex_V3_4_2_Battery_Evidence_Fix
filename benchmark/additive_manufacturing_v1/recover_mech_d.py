"""Deterministic Tables 1 and 4 recovery for AM-MECH-D."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.models import Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)

from .benchmark_common import load_locked, measurement, table_evidence, text_evidence


_MECH_BLOCK = re.compile(
    r"^(L-PBF-[123](?: \+ HT)?)\s*\nH\s*\n(\d+) ± (\d+)\s*\n(\d+) ± (\d+)\s*\n(\d+) ± (\d+)\s*\n"
    r"V\s*\n(\d+) ± (\d+)\s*\n(\d+) ± (\d+)\s*\n(\d+) ± (\d+)\s*$",
    re.MULTILINE,
)


def _three_values(label: str, text: str) -> list[float]:
    match = re.search(label + r"\s*\n(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)", text)
    if not match:
        raise ValueError(f"AM-MECH-D Table 1 row changed: {label}")
    return [float(match.group(i)) for i in range(1, 4)]


def _mechanical_rows(text: str) -> list[dict]:
    rows = []
    for block in _MECH_BLOCK.finditer(text):
        label = block.group(1)
        condition = label.replace(" + HT", "")
        heat_treated = "+ HT" in label
        for offset, orientation in ((2, "H"), (8, "V")):
            rows.append({
                "condition": condition,
                "orientation": orientation,
                "heat_treated": heat_treated,
                "yield_strength_mpa": float(block.group(offset)),
                "yield_uncertainty_mpa": float(block.group(offset + 1)),
                "uts_mpa": float(block.group(offset + 2)),
                "uts_uncertainty_mpa": float(block.group(offset + 3)),
                "elongation_pct": float(block.group(offset + 4)),
                "elongation_uncertainty_pct": float(block.group(offset + 5)),
            })
    return rows


def recover_mech_d():
    source, gold, lock = load_locked("mech_d_source_lock.json")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-MECH-D page count differs from lock")
        process_text = document[2].get_text().replace("ﬁ", "fi")
        feedstock_text = document[3].get_text().replace("ﬁ", "fi")
        method_text = document[4].get_text().replace("ﬁ", "fi")
        mechanical_text = document[15].get_text().replace("ﬁ", "fi")
    labels = {
        "laser_power_w": r"Laser Power P \(W\)",
        "scan_speed_mm_s": r"Scan speed V \(mm/s\)",
        "hatch_spacing_um": r"Hatch H \(µm\)",
        "spot_diameter_um": r"Spot Diameter D \(µm\)",
        "layer_thickness_um": r"Layer thickness t \(µm\)",
        "volumetric_energy_density_j_mm3": r"VED \(J/mm3\)",
    }
    columns = {key: _three_values(pattern, process_text) for key, pattern in labels.items()}
    builds = {
        f"L-PBF-{index + 1}": {key: values[index] for key, values in columns.items()}
        for index in range(3)
    }
    if builds != gold["builds"]:
        raise ValueError("AM-MECH-D recovered Table 1 values differ from frozen gold")
    rows = _mechanical_rows(mechanical_text)
    if rows != gold["rows"]:
        raise ValueError("AM-MECH-D recovered Table 4 values differ from frozen gold")
    if "room temperature" not in method_text or "3.33 × 10−3 s−1" not in method_text:
        raise ValueError("AM-MECH-D tensile-test context changed")

    feedstock_ev = text_evidence(4, "2. Materials and Methods", "commercial gas-atomized Inconel 625 powder")
    process_ev = text_evidence(3, "2. Materials and Methods", "Table 1. Laser-powder bed fusion (L-PBF) process parameters")
    post_ev = text_evidence(4, "2. Materials and Methods", "1100◦C, 3 h, under air")
    temp_ev = text_evidence(5, "2. Materials and Methods", "room temperature")
    rate_ev = text_evidence(5, "2. Materials and Methods", "3.33 × 10−3 s−1")
    materials = [DraftMaterial(
        local_id="feedstock", name="gas-atomized Inconel 625 powder", formula="Inconel 625",
        morphology={"shape": "mostly spherical", "particle_size_d10_um": 21, "particle_size_d50_um": 35, "particle_size_d90_um": 58},
        tags=["am_feedstock", "powder"], ownership="focal_work", evidence=[feedstock_ev],
    )]
    processes = []
    experiments = []
    recovered = []
    for index, row in enumerate(rows, start=1):
        condition = row["condition"]
        build_values = builds[condition]
        state = "HT" if row["heat_treated"] else "AB"
        label = f'{condition}-{row["orientation"]}-{state}'
        specimen = f"specimen_{index}"
        row_snippet = (
            f'{condition}{" + HT" if row["heat_treated"] else ""} {row["orientation"]} '
            f'{int(row["yield_strength_mpa"])} ± {int(row["yield_uncertainty_mpa"])} '
            f'{int(row["uts_mpa"])} ± {int(row["uts_uncertainty_mpa"])} '
            f'{int(row["elongation_pct"])} ± {int(row["elongation_uncertainty_pct"])}'
        )
        row_ev = table_evidence(16, "Table 4", label, "mechanical properties", row_snippet)
        materials.append(DraftMaterial(
            local_id=specimen, name=f"{label} Inconel 625 tensile specimen", formula="Inconel 625",
            tags=["am_part", f"source_sample:{label}"], ownership="focal_work", evidence=[row_ev],
        ))
        parameter_cells = {
            "laser_power": ("Laser Power P (W)", "laser_power_w", "W"),
            "scan_speed": ("Scan speed V (mm/s)", "scan_speed_mm_s", "mm/s"),
            "hatch_spacing": ("Hatch H (µm)", "hatch_spacing_um", "µm"),
            "spot_size": ("Spot Diameter D (µm)", "spot_diameter_um", "µm"),
            "layer_thickness": ("Layer thickness t (µm)", "layer_thickness_um", "µm"),
            "volumetric_energy_density": ("VED (J/mm3)", "volumetric_energy_density_j_mm3", "J/mm3"),
        }
        build_parameters = [
            measurement(
                property_name,
                str(int(build_values[value_key])),
                build_values[value_key],
                unit,
                table_evidence(3, "Table 1", row_label, condition, str(int(build_values[value_key]))),
                scientific_type=("reported_derived_metric" if property_name == "volumetric_energy_density" else "reported_process_parameter"),
            )
            for property_name, (row_label, value_key, unit) in parameter_cells.items()
        ] + [
            measurement("build_orientation", row["orientation"], row["orientation"], None, row_ev, scientific_type="reported_process_parameter", conditions={"orientation_definition": "H perpendicular to BD; V parallel to BD"}),
        ]
        processes.append(DraftProcess(
            local_id=f"build_{index}", name=f"{condition} build for {label}", family="laser_powder_bed_fusion",
            input_material_refs=["feedstock"], output_material_refs=[specimen], parameters=build_parameters,
            ownership="focal_work", evidence=[process_ev, row_ev],
        ))
        if row["heat_treated"]:
            processes.append(DraftProcess(
                local_id=f"post_{index}", name="recrystallization anneal and water quench", family="post_processing",
                input_material_refs=[specimen], output_material_refs=[specimen],
                parameters=[
                    measurement("post_process_temperature", "1100", 1100.0, "°C", post_ev, scientific_type="reported_process_parameter"),
                    measurement("post_process_time", "3", 3.0, "h", post_ev, scientific_type="reported_process_parameter"),
                    measurement("shielding_gas", "air", "air", None, post_ev, scientific_type="reported_process_parameter"),
                ],
                atmosphere="air", ownership="focal_work", evidence=[post_ev],
            ))
        outputs = []
        for property_name, value_key, uncertainty_key, unit, reported_term in (
            ("yield_strength", "yield_strength_mpa", "yield_uncertainty_mpa", "MPa", "σY"),
            ("ultimate_tensile_strength", "uts_mpa", "uts_uncertainty_mpa", "MPa", "UTS"),
            ("elongation", "elongation_pct", "elongation_uncertainty_pct", "%", "A%"),
        ):
            value = row[value_key]
            uncertainty = row[uncertainty_key]
            raw = f"{int(value)} ± {int(uncertainty)}"
            outputs.append(measurement(
                property_name, raw, value, unit, row_ev,
                scientific_type="reported_measurement", uncertainty=uncertainty,
                conditions={"reported_term": reported_term, "test_temperature": "room temperature", "specimen_orientation": row["orientation"]},
            ))
        conditions = [
            Measurement(property="test_temperature", raw_value="room temperature", value="room temperature", evidence=[temp_ev]),
            Measurement(property="strain_rate", raw_value="3.33 × 10−3", value=0.00333, unit="s^-1", evidence=[rate_ev]),
        ]
        experiments.append(DraftExperiment(
            local_id=f"tensile_{index}", experiment_type="uniaxial_tensile_test", material_refs=[specimen],
            target="tensile_response", conditions=conditions, outputs=outputs,
            protocol="room-temperature tensile test; two samples per condition", ownership="focal_work", evidence=[row_ev, temp_ev, rate_ev],
        ))
        recovered.append(row)

    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source_info["title"], doi=source_info["doi"], url=source_info["url"], year=source_info["year"], authors=source_info["authors"]),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={"case_id": gold["case_id"], "provider_invoked": False, "source_checksum": lock["source_sha256"], "mechanical_contract": "mechanical_v1"},
    )
    return assemble_archive(draft, domain="additive_manufacturing", model="deterministic_table_recovery"), builds, recovered
