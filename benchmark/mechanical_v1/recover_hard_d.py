"""Source-locked word-geometry recovery for MECH-HARD-D Table 4."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument

from .locked_case import load_locked_case


_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_COLUMNS = (("55Cr3", 280, 345), ("54SiCr6", 380, 445), ("52CrMoV4", 475, 545))


def _cell(words: list[tuple], left: float, right: float, y: float) -> tuple[str, float, float, tuple]:
    selected = sorted(
        (word for word in words if left < word[0] < right and abs(word[1] - y) < 1.8),
        key=lambda word: word[0],
    )
    if len(selected) != 3 or selected[1][4] != "±" or not all(
        _NUMBER.fullmatch(selected[index][4]) for index in (0, 2)
    ):
        raise ValueError(f"Hardness cell is ambiguous at y={y:.1f}, x={left}-{right}")
    raw = f"{selected[0][4]} ± {selected[2][4]}"
    bbox = (
        min(word[0] for word in selected), min(word[1] for word in selected),
        max(word[2] for word in selected), max(word[3] for word in selected),
    )
    return raw, float(selected[0][4]), float(selected[2][4]), bbox


def _evidence(table_id: str, row: int, column: str, text: str, bbox: tuple) -> Evidence:
    return Evidence(
        page=12, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=text,
        locator=(f"row={row};column={column};"
                 f"bbox={bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f}"),
    )


def recover_hard_d():
    source, gold, lock = load_locked_case("MECH-HARD-D")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Hardness PDF page count differs from source lock")
        method_text = document[2].get_text()
        method_text = method_text.replace("ﬁ", "fi")
        if "micro-Vickers hardness test, with 0.5 kg.f" not in method_text or "five indentations" not in method_text:
            raise ValueError("Hardness method/load/indentation count changed")
        page = document[11]
        text = page.get_text()
        if "Table 4. Hardness measurements determined at various cooling rates." not in text:
            raise ValueError("Reviewed Hardness table caption is missing")
        if "Micro-Vickers Hardness Tester" not in text:
            raise ValueError("Vickers scale is not established by the table")
        words = page.get_text("words")
        cooling_words = sorted(
            (word for word in words if 200 < word[0] < 230 and 445 < word[1] < 520
             and _NUMBER.fullmatch(word[4])), key=lambda word: word[1],
        )
        if len(cooling_words) != 6:
            raise ValueError("Hardness Table 4 row count changed")
        table_id = stable_id("tbl", lock["source_sha256"], "Table 4", 12)
        experiments = []
        recovered = []
        material_evidence = {}
        for material, left, right in _COLUMNS:
            header = next((word for word in words if word[4] == material and 430 < word[1] < 445), None)
            if header is None:
                raise ValueError(f"Hardness material header {material} is missing")
            material_evidence[material] = _evidence(
                table_id, 0, "sample", material,
                (header[0], header[1], header[2], header[3]),
            )
        for row_number, cooling_word in enumerate(cooling_words, 1):
            cooling_raw = cooling_word[4]
            cooling_rate = float(cooling_raw)
            for material, left, right in _COLUMNS:
                raw, value, uncertainty, bbox = _cell(words, left, right, cooling_word[1])
                evidence = _evidence(table_id, row_number, material, raw, bbox)
                conditions = {
                    "scientific_type": "reported_measurement",
                    "reported_term": "Micro-Vickers hardness",
                    "data_kind": "scalar", "curve_role": "scalar",
                    "hardness_scale": "Vickers", "test_load_kgf": 0.5,
                    "number_of_indents": 5, "dwell_time": "not_reported",
                    "cooling_rate": cooling_rate,
                    "cooling_rate_raw": f"{cooling_raw} °C/s",
                    "cooling_rate_unit": "°C/s",
                }
                experiments.append(DraftExperiment(
                    local_id=f"hard_table4_row_{row_number}_{material}",
                    experiment_type="micro_vickers_hardness",
                    material_refs=[f"hard_{material.lower()}"], ownership="focal_work",
                    conditions=[Measurement(
                        property="cooling_rate", raw_value=f"{cooling_raw} °C/s",
                        value=cooling_rate, unit="°C/s",
                    )],
                    outputs=[Measurement(
                        property="vickers_hardness", raw_value=raw, value=value,
                        unit="HV", uncertainty=uncertainty, uncertainty_unit="HV",
                        method="micro-Vickers; 0.5 kgf; five indentations",
                        conditions=conditions, evidence=[evidence],
                    )],
                    evidence=[evidence],
                ))
                recovered.append({
                    "table_row": row_number, "page": 12, "sample": material,
                    "cooling_rate": cooling_rate, "raw_cooling_rate": cooling_raw,
                    "raw_value": raw, "value": value, "uncertainty": uncertainty,
                    "unit": "HV", "table_id": table_id, "locator": evidence.locator,
                })
    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], year=source_info["year"],
            authors=source_info["authors"], url=source_info["url"],
        ),
        materials=[DraftMaterial(
            local_id=f"hard_{material.lower()}", name=material, ownership="focal_work",
            evidence=[material_evidence[material]],
        ) for material, _, _ in _COLUMNS],
        experiments=experiments,
        domain_values={
            "recovery_method": "locked_pdf_hardness_table4_word_geometry_v1",
            "table_id": table_id,
        },
    )
    return assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery"), recovered
