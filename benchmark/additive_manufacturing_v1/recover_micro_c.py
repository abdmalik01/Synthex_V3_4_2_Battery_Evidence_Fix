"""Deterministic Table 3 recovery for AM-MICRO-C."""

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
    r"^((?:UHT|HT450|HT750|HT1050)-(?:0|45|60|90))\s*\n"
    r"(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*\n"
    r"(\d+(?:\.\d+)?)\s*\n(\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)


def recover_micro_c():
    source, gold, lock = load_locked("micro_c_source_lock.json")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-MICRO-C page count differs from lock")
        method_text = document[2].get_text().replace("ﬁ", "fi")
        post_text = document[3].get_text().replace("ﬁ", "fi")
        table_text = document[8].get_text().replace("ﬁ", "fi")
    for phrase in ("laser power of 200 W", "scanning speed of 1000 mm/s", "layer thickness of 0.03 mm", "67"):
        if phrase not in method_text:
            raise ValueError(f"AM-MICRO-C build context changed: {phrase}")
    for temperature in ("450", "750", "1050"):
        if f"{temperature} ◦C/1.5 h/AC" not in post_text:
            raise ValueError(f"AM-MICRO-C heat-treatment context changed: {temperature}")
    parsed = [
        {"sample": match.group(1), "values": [float(match.group(i)) for i in range(2, 7)]}
        for match in _ROW.finditer(table_text)
    ]
    if parsed != gold["rows"]:
        raise ValueError("AM-MICRO-C recovered Table 3 values differ from frozen gold")

    feedstock_ev = text_evidence(3, "2.1. Materials and Preparation", "gas-atomized SS316L powder")
    build_ev = text_evidence(3, "2.1. Materials and Preparation", "laser power of 200 W, a scanning speed of 1000 mm/s, a layer thickness of 0.03 mm, and a scanning direction of 67◦")
    materials = [DraftMaterial(
        local_id="feedstock", name="gas-atomized SS316L powder", formula="316L",
        morphology={"shape": "spherical or ellipsoidal", "particle_size_range_um": [21, 53]},
        tags=["am_feedstock", "powder"], ownership="focal_work", evidence=[feedstock_ev],
    )]
    processes = []
    experiments = []
    for row in parsed:
        sample = row["sample"]
        state, orientation = sample.split("-", 1)
        specimen = f"specimen_{sample.lower()}"
        row_snippet = " ".join([sample, *[str(value) for value in row["values"]]])
        row_ev = table_evidence(9, "Table 3", sample, "RTC values", row_snippet)
        materials.append(DraftMaterial(
            local_id=specimen, name=f"{sample} SLM SS316L specimen", formula="316L",
            tags=["am_part", f"source_sample:{sample}"], ownership="focal_work", evidence=[row_ev],
        ))
        build_parameters = [
            measurement("laser_power", "200", 200.0, "W", build_ev, scientific_type="reported_process_parameter"),
            measurement("scan_speed", "1000", 1000.0, "mm/s", build_ev, scientific_type="reported_process_parameter"),
            measurement("layer_thickness", "0.03", 0.03, "mm", build_ev, scientific_type="reported_process_parameter"),
            measurement("rotation_angle", "67", 67.0, "°", build_ev, scientific_type="reported_process_parameter"),
            measurement("build_orientation", orientation, f"{orientation}°", None, row_ev, scientific_type="reported_process_parameter"),
            measurement("machine_model", "ISLM160", "ISLM160", None, text_evidence(3, "2.1. Materials and Preparation", "ISLM160"), scientific_type="reported_process_parameter"),
        ]
        processes.append(DraftProcess(
            local_id=f"build_{sample.lower()}", name=f"SLM build {sample}",
            family="laser_powder_bed_fusion", input_material_refs=["feedstock"],
            output_material_refs=[specimen], parameters=build_parameters,
            equipment="ISLM160", ownership="focal_work", evidence=[row_ev],
        ))
        if state != "UHT":
            temperature = float(state.removeprefix("HT"))
            post_snippet = f"{int(temperature)} ◦C/1.5 h/AC"
            post_ev = text_evidence(4, "2.2. Heat Treatment", post_snippet)
            processes.append(DraftProcess(
                local_id=f"post_{sample.lower()}", name=f"heat treatment {post_snippet}",
                family="post_processing", input_material_refs=[specimen], output_material_refs=[specimen],
                parameters=[
                    measurement("post_process_temperature", str(int(temperature)), temperature, "°C", post_ev, scientific_type="reported_process_parameter"),
                    measurement("post_process_time", "1.5", 1.5, "h", post_ev, scientific_type="reported_process_parameter"),
                ],
                atmosphere="air cooling", ownership="focal_work", evidence=[post_ev],
            ))
        outputs = []
        for plane, value in zip(gold["crystal_planes"], row["values"], strict=True):
            raw = str(value)
            outputs.append(measurement(
                "texture_coefficient", raw, value, "", row_ev,
                scientific_type="reported_measurement",
                conditions={"reported_term": "RTC", "crystal_plane": plane, "texture_kind": "build_crystallographic_texture"},
            ))
        experiments.append(DraftExperiment(
            local_id=f"xrd_{sample.lower()}", experiment_type="xrd_relative_texture_coefficient",
            material_refs=[specimen], target="crystallographic_texture", outputs=outputs,
            protocol="XRD relative texture coefficient", ownership="focal_work", evidence=[row_ev],
        ))

    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source_info["title"], doi=source_info["doi"], url=source_info["url"], year=source_info["year"], authors=source_info["authors"]),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={"case_id": gold["case_id"], "provider_invoked": False, "source_checksum": lock["source_sha256"], "scientific_boundaries": gold["scientific_boundaries"]},
    )
    return assemble_archive(draft, domain="additive_manufacturing", model="deterministic_table_recovery"), parsed
