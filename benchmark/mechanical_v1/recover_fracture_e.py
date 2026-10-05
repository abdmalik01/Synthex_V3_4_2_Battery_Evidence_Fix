"""Source-locked word-geometry recovery for MECH-FRACTURE-E Table 6."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)

from .locked_case import load_locked_case


_SAMPLE = re.compile(r"FT\((?:O|160|200|250)\)\d+\Z")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_TREATMENTS = {
    "O": ("original", "original treatment"),
    "160": ("tempered_160_c", "additionally tempered 160 °C"),
    "200": ("tempered_200_c", "additionally tempered 200 °C"),
    "250": ("tempered_250_c", "additionally tempered 250 °C"),
}


def _treatment(sample: str) -> tuple[str, str]:
    code = sample[sample.index("(") + 1:sample.index(")")]
    return _TREATMENTS[code]


def _evidence(table_id: str, row: int, sample: str, raw: str, bbox: tuple[float, ...]) -> Evidence:
    return Evidence(
        page=13, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=raw,
        locator=(f"row={row};sample={sample};"
                 f"bbox={bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f}"),
    )


def recover_fracture_e():
    source, gold, lock = load_locked_case("MECH-FRACTURE-E")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Fracture PDF page count differs from source lock")
        treatment_text = re.sub(
            r"\s+", " ", document[2].get_text().replace("ﬁ", "fi").replace("◦", "°")
        )
        if "Table 2. Heat treatment of OCHN3MFA grades" not in treatment_text:
            raise ValueError("Fracture treatment table is missing")
        if "Tempering alternatives: 160 °C/5 h, 200 °C/5 h, or 250 °C/5 h" not in treatment_text:
            raise ValueError("Fracture treatment alternatives changed")
        page = document[12]
        page_text = page.get_text()
        if "Table 6. Experimental values of the fracture toughness" not in page_text:
            raise ValueError("Fracture Table 6 caption is missing")
        if "Note: * KJU; † KJC." not in page_text:
            raise ValueError("Fracture Table 6 validity legend is missing")
        words = page.get_text("words")
        temperature_words = sorted(
            (word for word in words if 45 < word[0] < 75 and 595 < word[1] < 725
             and re.fullmatch(r"[−-]?\d+", word[4])),
            key=lambda word: word[1],
        )
        if len(temperature_words) != 9:
            raise ValueError("Fracture Table 6 temperature row count changed")
        table_id = stable_id("tbl", lock["source_sha256"], "Table 6", 13)
        recovered = []
        experiments = []
        seen_samples: set[str] = set()
        for row_number, temperature_word in enumerate(temperature_words, 1):
            temperature = int(temperature_word[4].replace("−", "-"))
            y = temperature_word[1]
            samples = sorted(
                (word for word in words if abs(word[1] - y) < 1.8 and _SAMPLE.fullmatch(word[4])),
                key=lambda word: word[0],
            )
            if not samples:
                raise ValueError(f"Fracture Table 6 has no specimens on row {row_number}")
            for sample_word in samples:
                sample = sample_word[4]
                if sample in seen_samples:
                    raise ValueError(f"Duplicate fracture specimen {sample}")
                seen_samples.add(sample)
                value_words = sorted(
                    (word for word in words if sample_word[2] <= word[0] < sample_word[2] + 75
                     and abs(word[1] - sample_word[1]) < 1.2 and _NUMBER.fullmatch(word[4])),
                    key=lambda word: word[0],
                )
                if len(value_words) != 1:
                    raise ValueError(f"Fracture value is ambiguous for {sample}")
                value_word = value_words[0]
                markers = [
                    word[4] for word in words
                    if value_word[2] <= word[0] < value_word[2] + 18
                    and abs(word[1] - value_word[1]) < 1.2 and word[4] in {"*", "†"}
                ]
                if len(markers) > 1:
                    raise ValueError(f"Fracture metric marker is ambiguous for {sample}")
                marker = markers[0] if markers else None
                metric = "K_JU" if marker == "*" else "K_JC" if marker == "†" else "K_IC"
                validity = {
                    "K_IC": "valid_linear_elastic_plane_strain",
                    "K_JC": "conditional_j_integral_derived",
                    "K_JU": "invalid_rough_fracture_toughness",
                }[metric]
                scientific_type = "reported_derived_metric" if metric in {"K_JC", "K_JU"} else "reported_measurement"
                treatment, treatment_label = _treatment(sample)
                raw = value_word[4]
                bbox = (value_word[0], value_word[1], value_word[2], value_word[3])
                evidence = _evidence(table_id, row_number, sample, raw, bbox)
                local_material = f"fracture_{treatment}"
                output = Measurement(
                    property="fracture_toughness", raw_value=raw, value=float(raw),
                    unit="MPa*sqrt(m)", method="pre-cracked Charpy V-notch fracture test",
                    conditions={
                        "scientific_type": scientific_type, "reported_term": metric,
                        "data_kind": "scalar", "curve_role": "scalar", "sample": sample,
                        "specimen_type": "pre-cracked Charpy V-notch",
                        "processing_state": treatment, "processing_state_label": treatment_label,
                        "test_temperature_c": temperature, "reported_metric": metric,
                        "validity": validity,
                    },
                    evidence=[evidence],
                )
                experiments.append(DraftExperiment(
                    local_id=f"fracture_table6_{sample}", experiment_type="fracture_toughness",
                    material_refs=[local_material], ownership="focal_work",
                    conditions=[Measurement(
                        property="test_temperature", raw_value=f"{temperature_word[4]} °C",
                        value=temperature, unit="°C",
                    )],
                    outputs=[output], evidence=[evidence],
                ))
                recovered.append({
                    "table_row": row_number, "page": 13, "sample": sample,
                    "treatment": treatment, "test_temperature_c": temperature,
                    "raw_value": raw, "value": float(raw), "unit": "MPa*sqrt(m)",
                    "reported_metric": metric, "validity": validity,
                    "table_id": table_id, "locator": evidence.locator,
                })

    source_info = gold["source"]
    materials = []
    processes = []
    for code, (treatment, treatment_label) in _TREATMENTS.items():
        material_id = f"fracture_{treatment}"
        material_evidence = Evidence(
            page=3, source_type="table", original_source_type="table_reported",
            verbatim_match=True, text_snippet=(
                "original grade-conventional treatment" if code == "O"
                else f"Tempering alternatives: 160 °C/5 h, 200 °C/5 h, or 250 °C/5 h"
            ),
            locator="Table 2",
        )
        materials.append(DraftMaterial(
            local_id=material_id, name=f"OCHN3MFA steel; {treatment_label}",
            ownership="focal_work", tags=["OCHN3MFA", treatment], evidence=[material_evidence],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{treatment}", name=treatment_label, family="heat_treatment",
            material_refs=[material_id], ownership="focal_work", evidence=[material_evidence],
        ))
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], year=source_info["year"],
            authors=source_info["authors"], url=source_info["url"],
        ),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={
            "recovery_method": "locked_pdf_fracture_table6_word_geometry_v1",
            "table_id": table_id,
            "metric_policy": "preserve_K_IC_K_JC_K_JU_and_reported_validity",
        },
    )
    return assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery"), recovered
