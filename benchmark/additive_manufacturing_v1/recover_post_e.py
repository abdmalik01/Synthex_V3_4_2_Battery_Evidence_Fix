"""Deterministic Tables 2 and 4 recovery for AM-POST-E."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.models import Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument

from .benchmark_common import load_locked, measurement, table_evidence, text_evidence


def _table4_rows(text: str, gold: dict) -> list[dict]:
    rows = []
    for expected in gold["rows"]:
        match = re.search(
            rf'{re.escape(expected["sample"])}\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)',
            text,
        )
        if not match:
            raise ValueError(f'AM-POST-E Table 4 row missing: {expected["sample"]}')
        rows.append({
            "sample": expected["sample"],
            "orientation": expected["orientation"],
            "treatment": expected["treatment"],
            "yield_strength_mpa": float(match.group(1)),
            "uts_mpa": float(match.group(2)),
            "elongation": float(match.group(4)),
        })
    return rows


def recover_post_e():
    source, gold, lock = load_locked("post_e_source_lock.json")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-POST-E page count differs from lock")
        method_text = (document[1].get_text() + document[2].get_text()).replace("ﬁ", "fi")
        build_text = document[2].get_text().replace("ﬁ", "fi")
        test_text = document[3].get_text().replace("ﬁ", "fi")
        result_text = document[7].get_text().replace("ﬁ", "fi")
    build = {
        "family": "directed_energy_deposition",
        "beam_power_w": float(re.search(r"Beam Power\s+(\d+) W", build_text).group(1)),
        "beam_width_um": float(re.search(r"Beam width\s+(\d+) µm", build_text).group(1)),
        "powder_feed_rate_g_min": float(re.search(r"Powder feeding\s+(\d+) g/min", build_text).group(1)),
        "atmosphere": re.search(r"Atmosphere\s+(\w+)", build_text).group(1),
        "scan_strategy": re.search(r"Strategy\s+(\w+)", build_text).group(1).casefold(),
    }
    if build != gold["build"]:
        raise ValueError("AM-POST-E Table 2 build values differ from frozen gold")
    rows = _table4_rows(result_text, gold)
    if rows != gold["rows"]:
        raise ValueError("AM-POST-E Table 4 values differ from frozen gold")
    if not re.search(r"1038 .C", method_text) or not re.search(r"482 .C", result_text) or "10−3/s" not in test_text:
        raise ValueError("AM-POST-E treatment/test context changed")

    feedstock_ev = table_evidence(3, "Table 1", "17-4PH metallic powder", "composition", "Chemical composition of 17-4PH metallic powder")
    build_ev = table_evidence(3, "Table 2", "DED conditions", "all", "Beam Power 425 W; Beam width 800 µm; Powder feeding 3 g/min; Atmosphere Ar; Strategy Zigzag")
    aging_ev = text_evidence(8, "3.3. Solid-Solution and Heat-Treatment Path", "aging treatment at 482 ◦C for an hour")
    solution_ev = text_evidence(3, "2.1. Additive Manufacturing and Heat-Treatments", "solid-solution treatment entails heating to 1038 ◦C for 30 min, residing for an hour, and finally water-quenching")
    test_ev = text_evidence(4, "2.2. Material Characterization", "10−3/s tensile test")
    materials = [DraftMaterial(
        local_id="feedstock", name="17-4PH metallic powder", formula="17-4PH",
        tags=["am_feedstock", "powder"], ownership="focal_work", evidence=[feedstock_ev],
    )]
    processes = []
    experiments = []
    for row in rows:
        sample = row["sample"]
        initial = f"asbuilt_{sample}"
        final = initial if row["treatment"] == "AB" else f"post_{sample}"
        row_snippet = f'{sample} {int(row["yield_strength_mpa"])} {int(row["uts_mpa"])} {row["elongation"]}'
        row_ev = table_evidence(8, "Table 4", sample, "tensile properties", row_snippet)
        orientation_snippet = (
            "Parallel to building direction (Vertical)"
            if row["orientation"] == "vertical"
            else "Perpendicular to building direction (Horizontal)"
        )
        orientation_ev = table_evidence(8, "Table 4", sample, "Loading Direction", orientation_snippet)
        materials.append(DraftMaterial(
            local_id=initial, name=f"{sample} as-built 17-4PH DED specimen", formula="17-4PH",
            tags=["am_part", "as_built", f"orientation:{row['orientation']}"], ownership="focal_work", evidence=[row_ev],
        ))
        if final != initial:
            materials.append(DraftMaterial(
                local_id=final, name=f"{sample} post-processed 17-4PH specimen", formula="17-4PH",
                tags=["am_part", f"treatment:{row['treatment']}"], ownership="focal_work", evidence=[row_ev],
            ))
        build_parameters = [
            measurement("laser_power", "425", 425.0, "W", build_ev, scientific_type="reported_process_parameter", conditions={"reported_term": "Beam Power"}),
            measurement("beam_diameter", "800", 800.0, "µm", build_ev, scientific_type="reported_process_parameter", conditions={"reported_term": "Beam width"}),
            measurement("powder_feed_rate", "3", 3.0, "g/min", build_ev, scientific_type="reported_process_parameter"),
            measurement("shielding_gas", "Ar", "Ar", None, build_ev, scientific_type="reported_process_parameter"),
            measurement("scan_strategy", "Zigzag", "zigzag", None, build_ev, scientific_type="reported_process_parameter"),
            measurement("build_orientation", row["orientation"], row["orientation"], None, orientation_ev, scientific_type="reported_process_parameter"),
        ]
        processes.append(DraftProcess(
            local_id=f"build_{sample}", name=f"DED build for {sample}", family="directed_energy_deposition",
            input_material_refs=["feedstock"], output_material_refs=[initial], parameters=build_parameters,
            atmosphere="Ar", ownership="focal_work", evidence=[build_ev, row_ev],
        ))
        current = initial
        treatment = gold["treatments"][row["treatment"]]
        for index, step in enumerate(treatment["steps"], start=1):
            is_last = index == len(treatment["steps"])
            output = final if is_last else f"intermediate_{sample}_{index}"
            if not is_last:
                materials.append(DraftMaterial(
                    local_id=output, name=f"{sample} intermediate post-process state {index}", formula="17-4PH",
                    tags=["am_part", "intermediate_state"], ownership="focal_work", evidence=[solution_ev],
                ))
            evidence = solution_ev if step["temperature_c"] == 1038 else aging_ev
            raw_time = "an hour"
            processes.append(DraftProcess(
                local_id=f"post_{sample}_{index}", name=("solid-solution treatment and water quench" if step["temperature_c"] == 1038 else "direct aging and air cooling"),
                family="post_processing", input_material_refs=[current], output_material_refs=[output],
                parameters=[
                    measurement("post_process_temperature", str(step["temperature_c"]), float(step["temperature_c"]), "°C", evidence, scientific_type="reported_process_parameter"),
                    measurement("post_process_time", raw_time, 1.0, "h", evidence, scientific_type="reported_process_parameter"),
                ], atmosphere=step["cooling"], ownership="focal_work", evidence=[evidence],
            ))
            current = output
        outputs = [
            measurement("yield_strength", str(int(row["yield_strength_mpa"])), row["yield_strength_mpa"], "MPa", row_ev, scientific_type="reported_measurement", conditions={"reported_term": "0.2% Offset Yield Strength"}),
            measurement("ultimate_tensile_strength", str(int(row["uts_mpa"])), row["uts_mpa"], "MPa", row_ev, scientific_type="reported_measurement", conditions={"reported_term": "Tensile Strength"}),
            measurement("elongation", str(row["elongation"]), row["elongation"], "1", row_ev, scientific_type="reported_measurement", conditions={"reported_term": "Total Elongation"}),
        ]
        experiments.append(DraftExperiment(
            local_id=f"tensile_{sample}", experiment_type="uniaxial_tensile_test", material_refs=[final],
            target="tensile_response", conditions=[Measurement(property="strain_rate", raw_value="10−3", value=0.001, unit="s^-1", evidence=[test_ev])],
            outputs=outputs, protocol="tensile testing at 10^-3 s^-1", ownership="focal_work", evidence=[row_ev, test_ev],
        ))
    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source_info["title"], doi=source_info["doi"], url=source_info["url"], year=source_info["year"], authors=source_info["authors"]),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={"case_id": gold["case_id"], "provider_invoked": False, "source_checksum": lock["source_sha256"], "mechanical_contract": "mechanical_v1"},
    )
    return assemble_archive(draft, domain="additive_manufacturing", model="deterministic_table_recovery"), rows
