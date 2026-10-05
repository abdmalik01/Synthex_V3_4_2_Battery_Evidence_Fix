"""Deterministic word-geometry recovery for PV-GOLD-A Table 2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
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


CASE_DIR = Path(__file__).resolve().parent
_COLUMNS = {
    "open_circuit_voltage": (215.0, 270.0, "V"),
    "short_circuit_current": (280.0, 330.0, "mA"),
    "short_circuit_current_density": (335.0, 400.0, "mA/cm2"),
    "fill_factor": (405.0, 460.0, "%"),
    "power_conversion_efficiency": (465.0, 520.0, "%"),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_evidence(page: int, snippet: str, section: str) -> Evidence:
    return Evidence(
        page=page,
        section=section,
        source_type="text",
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=snippet,
        locator=f"page={page};section={section}",
    )


def _table_evidence(table_id: str, label: str, column: str, words: list[tuple]) -> Evidence:
    raw = " ".join(word[4] for word in words)
    boxes = ";".join(
        f"{word[0]:.1f},{word[1]:.1f},{word[2]:.1f},{word[3]:.1f}" for word in words
    )
    return Evidence(
        page=8,
        source_type="table",
        original_source_type="native_text",
        verbatim_match=True,
        table_id=table_id,
        text_snippet=raw,
        locator=f"row={label};column={column};bbox={boxes}",
    )


def _row_labels(words: list[tuple]) -> list[tuple[str, str, float]]:
    labels: list[tuple[str, str, float]] = []
    bare = next(word for word in words if word[4] == "Bare" and word[0] < 110)
    labels.append(("bare", "Bare cell (Before CMP)", bare[1]))
    for minutes in (5, 10, 15):
        token = next(
            word for word in words
            if word[4] == str(minutes) and 150 < word[0] < 175 and 155 < word[1] < 220
        )
        labels.append((f"cmp_{minutes}_min", f"After CMP treatment {minutes} min", token[1]))
    return labels


def _extract_rows(page, table_id: str) -> list[dict]:
    words = page.get_text("words")
    rows: list[dict] = []
    for variant, label, row_y in _row_labels(words):
        cells: dict[str, dict] = {}
        for property_name, (left, right, unit) in _COLUMNS.items():
            cell_words = sorted(
                [word for word in words if left < word[0] < right and abs(word[1] - row_y) < 8.0],
                key=lambda word: word[1],
            )
            if len(cell_words) != 2 or not cell_words[1][4].startswith("("):
                raise ValueError(f"Ambiguous PV-GOLD-A Table 2 cell: {label}/{property_name}")
            value = float(cell_words[0][4])
            uncertainty = float(cell_words[1][4].strip("()"))
            cells[property_name] = {
                "value": value,
                "uncertainty": uncertainty,
                "unit": unit,
                "raw": f"{cell_words[0][4]} {cell_words[1][4]}",
                "evidence": _table_evidence(table_id, label, property_name, cell_words),
            }
        treatment = None if variant == "bare" else float(variant.split("_")[1])
        rows.append({
            "variant": variant,
            "label": label,
            "treatment_time_min": treatment,
            "cells": cells,
        })
    return rows


def _result_measurement(property_name: str, cell: dict, context: dict) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=cell["raw"],
        value=cell["value"],
        unit=cell["unit"],
        uncertainty=cell["uncertainty"],
        uncertainty_unit=cell["unit"],
        qualifier="exact",
        conditions={
            "scientific_type": "reported_measurement",
            "data_kind": "mean_with_standard_deviation",
            **context,
        },
        evidence=[cell["evidence"]],
    )


def recover_gold_a():
    lock = _read(CASE_DIR / "source_lock.json")
    gold = _read(CASE_DIR / lock["gold_file"])
    source = CASE_DIR / lock["source_file"]
    if _sha256(source) != lock["source_sha256"]:
        raise ValueError("PV-GOLD-A source checksum differs from the source lock")
    if _sha256(CASE_DIR / lock["gold_file"]) != lock["gold_sha256"]:
        raise ValueError("PV-GOLD-A gold checksum differs from the source lock")

    with pymupdf.open(source) as document:
        if len(document) != lock["page_count"] or len(document) != gold["source"]["page_count"]:
            raise ValueError("PV-GOLD-A PDF page count differs from the source lock")
        surface_text = re.sub(r"\s+", " ", document[1].get_text().replace("ﬁ", "fi"))
        fabrication_text = re.sub(r"\s+", " ", document[2].get_text().replace("ﬁ", "fi").replace("ﬃ", "ffi"))
        table_page = document[7]
        table_text = re.sub(r"\s+", " ", table_page.get_text().replace("ﬁ", "fi").replace("ﬃ", "ffi"))
        if not all(term in surface_text for term in ("FTO glass", "chemical mechanical polishing", "5 min")):
            raise ValueError("PV-GOLD-A surface-treatment source context changed")
        if not all(term in fabrication_text for term in (
            "CH3NH3PbI3", "TiO2 layer on the FTO substrate", "Spiro-MeOTAD",
            "metal electrode (Au)", "AM 1.5 G (100 mW/cm2)",
        )):
            raise ValueError("PV-GOLD-A fabrication or measurement context changed")
        if not all(term in table_text for term in (
            "Table 2. Photovoltaic performance parameters", "Bare cell (Before CMP)",
            "After CMP treatment", "Standard Deviation",
        )):
            raise ValueError("PV-GOLD-A Table 2 caption or row structure changed")
        table_id = stable_id("tbl", lock["source_sha256"], "Table 2", 8)
        recovered = _extract_rows(table_page, table_id)

    recovered_values = []
    for row in recovered:
        payload = {
            "variant": row["variant"],
            "label": row["label"],
            "treatment_time_min": row["treatment_time_min"],
        }
        for property_name, cell in row["cells"].items():
            payload[property_name] = [cell["value"], cell["uncertainty"], cell["unit"]]
        recovered_values.append(payload)
    if recovered_values != gold["rows"]:
        raise ValueError("PV-GOLD-A recovered Table 2 values differ from frozen gold")

    glass_evidence = _text_evidence(2, "FTO glass", "2.1. Surface Treatment")
    fabrication_evidence = _text_evidence(
        3,
        "To make perovskite solar cells, we used a two-step spin-coating procedure to form CH3NH3PbI3 [19,20]. A lab-made TiO2 paste was used for the mesoporous and compact TiO2 layer on the FTO substrate. After the PbI2 solution was spin-coated on the mesoporous TiO2 layer, a CH3NH3I (MAI) solution in 2-propanol was loaded on the PbI2-coated substrate. Then, the Spiro-MeOTAD was spin-coated on the CH3NH3PbI3 perovskite layer. The metal electrode (Au) was deposited by the thermal evaporator.",
        "2.2. Fabrication of Perovskite Solar Cells",
    )
    measurement_evidence = _text_evidence(
        3,
        "current–voltage (J–V) solar simulator (McScience Company K3400) at AM 1.5 G (100 mW/cm2)",
        "2.3. Measurements",
    )
    materials = [
        DraftMaterial(local_id="glass", name="glass substrate", tags=["substrate"], ownership="focal_work", evidence=[glass_evidence]),
        DraftMaterial(local_id="tio2", name="TiO2 electron-transport layer", formula="TiO2", tags=["etl"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="mapbi3", name="CH3NH3PbI3 perovskite absorber", formula="CH3NH3PbI3", tags=["absorber"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="spiro", name="Spiro-MeOTAD hole-transport layer", tags=["htl"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="au", name="gold electrode", formula="Au", tags=["electrode"], ownership="focal_work", evidence=[fabrication_evidence]),
    ]
    devices = []
    processes = []
    experiments = []
    context = gold["measurement_context"]
    for row in recovered:
        variant = row["variant"]
        row_evidence = next(iter(row["cells"].values()))["evidence"]
        fto_ref = f"fto_{variant}"
        device_ref = f"device_{variant}"
        materials.append(DraftMaterial(
            local_id=fto_ref,
            name=f"FTO transparent electrode ({row['label']})",
            tags=["transparent_electrode", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[row_evidence],
        ))
        layer_refs = [
            ("substrate", "glass"),
            ("transparent_electrode", fto_ref),
            ("etl", "tio2"),
            ("absorber", "mapbi3"),
            ("htl", "spiro"),
            ("electrode", "au"),
        ]
        devices.append(DraftDevice(
            local_id=device_ref,
            name=f"Perovskite solar cell — {row['label']}",
            device_type="solar_cell",
            layer_stack=[
                DraftDeviceLayer(
                    sequence_index=index,
                    role=role,
                    material_ref=material_ref,
                    evidence=[fabrication_evidence],
                )
                for index, (role, material_ref) in enumerate(layer_refs)
            ],
            configuration={
                "architecture": "glass/FTO/TiO2/CH3NH3PbI3/Spiro-MeOTAD/Au",
                "variant": variant,
                "cmp_treatment_time_min": row["treatment_time_min"] if row["treatment_time_min"] is not None else "not applied",
            },
            tags=["perovskite_solar_cell", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[fabrication_evidence, row_evidence],
        ))
        parameters = []
        if row["treatment_time_min"] is not None:
            raw_time = f"{int(row['treatment_time_min'])} min"
            time_evidence = row_evidence.model_copy(update={"text_snippet": row["label"]})
            parameters.append(Measurement(
                property="processing_time",
                raw_value=raw_time,
                value=row["treatment_time_min"],
                unit="min",
                qualifier="exact",
                conditions={
                    "scientific_type": "reported_process_parameter",
                    "data_kind": "scalar",
                    "process_step": "chemical-mechanical polishing",
                },
                evidence=[time_evidence],
            ))
        processes.append(DraftProcess(
            local_id=f"fabricate_{variant}",
            name=f"Fabricate {row['label']} perovskite solar cell",
            family="perovskite_solar_cell_fabrication",
            input_material_refs=[material_ref for _, material_ref in layer_refs],
            output_device_refs=[device_ref],
            parameters=parameters,
            equipment="spin coater and thermal evaporator",
            ownership="focal_work",
            evidence=[fabrication_evidence, row_evidence],
        ))
        outputs = [
            _result_measurement(property_name, cell, context)
            for property_name, cell in row["cells"].items()
        ]
        experiments.append(DraftExperiment(
            local_id=f"jv_{variant}",
            experiment_type="current_voltage_photovoltaic_performance",
            device_refs=[device_ref],
            target="photovoltaic performance",
            outputs=outputs,
            protocol="current-voltage (J-V) solar simulator at AM 1.5 G (100 mW/cm2)",
            ownership="focal_work",
            evidence=[measurement_evidence, row_evidence],
        ))

    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"],
            doi=source_info["doi"],
            url=source_info["url"],
            year=source_info["year"],
            authors=source_info["authors"],
        ),
        materials=materials,
        devices=devices,
        processes=processes,
        experiments=experiments,
        domain_values={
            "paper_types": ["device_fabrication", "device_architecture", "photovoltaic_performance"],
            "recovery_method": "locked_pdf_table2_word_geometry_v1",
            "source_checksum": lock["source_sha256"],
            "table_id": table_id,
            "provider_invoked": False,
            "active_area": "not reported",
            "scan_direction": "not reported",
        },
    )
    archive = assemble_archive(draft, domain="photovoltaics", model="deterministic_table_recovery")
    return archive, recovered_values
