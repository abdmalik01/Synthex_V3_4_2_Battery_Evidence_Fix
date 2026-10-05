"""Deterministic Tables 1 and 3 calculation recovery for AM-COMPUTE-F."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftCalculation, DraftMaterial, DraftSource, ExtractedDocument

from .benchmark_common import load_locked, measurement, table_evidence, text_evidence


def recover_compute_f():
    source, gold, lock = load_locked("compute_f_source_lock.json")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-COMPUTE-F page count differs from lock")
        method_text = "\n".join(document[index].get_text().replace("ﬁ", "fi") for index in (18, 19, 20, 24, 25))
        input_text = document[21].get_text().replace("ﬁ", "fi")
        output_text = document[22].get_text().replace("ﬁ", "fi")
    inputs = {}
    for material in ("Ti6Al4v", "SS316L"):
        column = 1 if material == "Ti6Al4v" else 2
        values = {}
        for label, key in (("Power", "laser_power_w"), ("Speed", "scan_speed_mm_s"), ("Laser spot size", "spot_size_um"), ("Layer thickness", "layer_thickness_um")):
            block = re.search(rf"{re.escape(label)}\s+([\d.]+)\s+([\d.]+)", input_text)
            if not block:
                raise ValueError(f"AM-COMPUTE-F Table 1 field missing: {label}")
            values[key] = float(block.group(column))
        inputs[material.casefold()] = values
    rows = []
    for expected in gold["rows"]:
        match = re.search(
            rf'{re.escape(expected["material"])}\s+(\d+)\s+(\d+)\s+(\d+) ± (\d+)\s+(\d+) ± (\d+)',
            output_text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(f'AM-COMPUTE-F Table 3 row missing: {expected["material"]}')
        values = inputs[expected["material"].casefold()]
        row = {
            "material": expected["material"], **values,
            "measured_melt_pool_width_um": float(match.group(3)),
            "measured_uncertainty_um": float(match.group(4)),
            "predicted_melt_pool_width_um": float(match.group(5)),
            "predicted_uncertainty_um": float(match.group(6)),
        }
        rows.append(row)
    if rows != gold["rows"]:
        raise ValueError("AM-COMPUTE-F recovered values differ from frozen gold")
    if "enthalpy method" not in method_text or "Gaussian intensity profile" not in method_text:
        raise ValueError("AM-COMPUTE-F method context changed")

    method_ev = text_evidence(25, "6. Validation", "meso-scale simulation requires approximately 30 min of wall clock time")
    heat_ev = text_evidence(26, "8. Discussion", "only the Gaussian intensity profile has been used")
    materials = []
    calculations = []
    for row in rows:
        material = row["material"]
        local_id = f"material_{material.casefold()}"
        row_snippet = f'{material} {int(row["laser_power_w"])} {int(row["scan_speed_mm_s"])} {int(row["measured_melt_pool_width_um"])} ± {int(row["measured_uncertainty_um"])} {int(row["predicted_melt_pool_width_um"])} ± {int(row["predicted_uncertainty_um"])}'
        row_ev = table_evidence(23, "Table 3", material, "model validation", row_snippet)
        input_ev = table_evidence(22, "Table 1", material, "model inputs", f'{material} {int(row["laser_power_w"])} {int(row["scan_speed_mm_s"])} {row["spot_size_um"]} {int(row["layer_thickness_um"])}')
        materials.append(DraftMaterial(
            local_id=local_id, name=f"{material} PBF-LB/M model material", formula=material,
            tags=["computational_material"], ownership="focal_work", evidence=[input_ev],
        ))
        parameters = [
            measurement("laser_power", str(int(row["laser_power_w"])), row["laser_power_w"], "W", input_ev, scientific_type="reported_process_parameter"),
            measurement("scan_speed", str(int(row["scan_speed_mm_s"])), row["scan_speed_mm_s"], "mm/s", input_ev, scientific_type="reported_process_parameter"),
            measurement("spot_size", str(row["spot_size_um"]), row["spot_size_um"], "µm", input_ev, scientific_type="reported_process_parameter"),
            measurement("layer_thickness", str(int(row["layer_thickness_um"])), row["layer_thickness_um"], "µm", input_ev, scientific_type="reported_process_parameter"),
        ]
        output = measurement(
            "melt_pool_width", str(int(row["predicted_melt_pool_width_um"])), row["predicted_melt_pool_width_um"], "µm", row_ev,
            scientific_type="simulation_result", uncertainty=row["predicted_uncertainty_um"],
            conditions={"reported_term": "Model Output", "validation_measurement_um": row["measured_melt_pool_width_um"], "validation_uncertainty_um": row["measured_uncertainty_um"]},
        )
        calculations.append(DraftCalculation(
            local_id=f"calculation_{material.casefold()}", calculation_type="multi_scale_thermal_pbf_simulation",
            material_refs=[local_id], method=gold["method"]["model_family"],
            model={**gold["method"], "validation_modality": "in_line_monitoring"},
            parameters=parameters, outputs=[output], ownership="focal_work", evidence=[method_ev, heat_ev, input_ev, row_ev],
        ))
    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source_info["title"], doi=source_info["doi"], url=source_info["url"], year=source_info["year"], authors=source_info["authors"]),
        materials=materials, calculations=calculations,
        domain_values={"case_id": gold["case_id"], "provider_invoked": False, "source_checksum": lock["source_sha256"], "computational_contract": "calculation_only"},
    )
    return assemble_archive(draft, domain="additive_manufacturing", model="deterministic_table_recovery"), rows
