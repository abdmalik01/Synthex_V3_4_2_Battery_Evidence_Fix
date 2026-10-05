"""Value-agnostic word-geometry recovery of locked Creep Table 2."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)
from synthex_platform.visual.tables import extract_tables

from .locked_case import load_locked_case


_NUMERIC = re.compile(r"\d+(?:\.\d+)?\Z")
_COLUMNS = (
    ("rupture_time", "t_rup", "h", 320, 380),
    ("rupture_strain", "epsilon_rup", "%", 380, 440),
    ("time_to_specific_strain", "t_1%", "h", 440, 505),
)


def _cell(words: list[tuple], left: float, right: float, y: float) -> tuple | None:
    matches = [word for word in words if left <= word[0] < right and abs(word[1] - y) < 1.6]
    if len(matches) != 1:
        return None
    return matches[0]


def _table_evidence(page: int, table_id: str, row: int, column: str, word: tuple) -> Evidence:
    return Evidence(
        page=page, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=word[4],
        locator=(
            f"row={row};column={column};"
            f"bbox={word[0]:.1f},{word[1]:.1f},{word[2]:.1f},{word[3]:.1f}"
        ),
    )


def recover_creep_b():
    source, gold, lock = load_locked_case("MECH-CREEP-B")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Creep source page count differs from lock")
        page_number = lock["selected_page"]
        page = document[page_number - 1]
        content = page.get_text()
        if "Table 2." not in content or "stress-rupture test data" not in content:
            raise ValueError("Creep Table 2 caption missing from reviewed page")
        words = page.get_text("words")
        header = [word[4] for word in words if 110 <= word[1] <= 126]
        if not all(token in header for token in ("Temperature", "Stress", "Remark")):
            raise ValueError("Creep Table 2 headers changed")
        stress_words = sorted(
            (word for word in words if 260 < word[0] < 320 and 130 < word[1] < 325
             and _NUMERIC.fullmatch(word[4])), key=lambda word: word[1],
        )
        temperature_words = sorted(
            (word for word in words if 180 < word[0] < 240 and 130 < word[1] < 325
             and re.fullmatch(r"\d{3}", word[4])), key=lambda word: word[1],
        )
        if len(stress_words) != 16 or len(temperature_words) != 4:
            raise ValueError("Creep Table 2 row or temperature-group count changed")
        # Full-width rules separate temperature blocks; vertical word distance
        # alone is not reliable because a two-row block can have the same gap.
        rules = sorted(
            drawing["rect"].y0 for drawing in page.get_drawings()
            if drawing["rect"].width > 300 and 125 < drawing["rect"].y0 < 335
        )
        groups = [
            [word for word in stress_words if top < word[1] < bottom]
            for top, bottom in zip(rules, rules[1:])
        ]
        if len(rules) != 5 or len(groups) != len(temperature_words) or any(not group for group in groups):
            raise ValueError("Creep Table 2 temperature grouping is ambiguous")
        for group, temperature in zip(groups, temperature_words):
            if not group[0][1] <= temperature[1] <= group[-1][1]:
                raise ValueError("Creep test temperature is not inside its row group")

        tables = [table for table in extract_tables(source) if (
            table.page == page_number and table.table_number == "2"
        )]
        if len(tables) != 1:
            raise ValueError("Creep Table 2 stable table ID is unavailable")
        table_id = tables[0].table_id

        material_id = "creep_alloy_617_weldment"
        source_info = gold["source"]
        material = DraftMaterial(
            local_id=material_id, name=gold["gold_basis"]["sample"],
            ownership="focal_work", tags=["alloy_617", "diffusion_welded"],
            evidence=[Evidence(
                page=1, source_type="text", original_source_type="native_text",
                verbatim_match=True, text_snippet="Creep Behavior of Diffusion-Welded Alloy 617",
            )],
        )
        process = DraftProcess(
            local_id="creep_diffusion_welding", name="diffusion welding",
            family="joining", material_refs=[material_id], ownership="focal_work",
            evidence=[Evidence(
                page=1, source_type="text", original_source_type="native_text",
                verbatim_match=True, text_snippet="diffusion welding",
            )],
        )
        experiments = []
        recovered = []
        omitted = []
        row_number = 0
        for group, temperature_word in zip(groups, temperature_words):
            temperature = int(temperature_word[4])
            for stress_word in group:
                row_number += 1
                y = stress_word[1]
                remark = _cell(words, 505, 550, y)
                if remark is None:
                    raise ValueError(f"Creep Table 2 remark missing on row {row_number}")
                if remark[4] == "N/A":
                    omitted.append({
                        "table_row": row_number, "temperature": temperature,
                        "applied_stress": float(stress_word[4]), "reason": "remark_N/A",
                    })
                    continue
                if remark[4] != "-":
                    raise ValueError(f"Creep Table 2 remark unclear on row {row_number}")
                stress = float(stress_word[4])
                outputs = []
                for property_name, reported_term, unit, left, right in _COLUMNS:
                    word = _cell(words, left, right, y)
                    if word is None:
                        raise ValueError(f"Creep Table 2 cell missing on row {row_number}")
                    raw = word[4]
                    if raw == "-":
                        continue
                    if not _NUMERIC.fullmatch(raw):
                        raise ValueError(f"Creep Table 2 numeric cell unclear: {raw!r}")
                    evidence = _table_evidence(page_number, table_id, row_number, property_name, word)
                    outputs.append(Measurement(
                        property=property_name, raw_value=raw, value=float(raw), unit=unit,
                        conditions={
                            "reported_term": reported_term, "scientific_type": "reported_measurement",
                            "data_kind": "scalar", "processing_state": "diffusion_welded",
                            "test_temperature": temperature, "temperature": temperature,
                            "applied_stress": stress, "test_environment": "ambient air",
                        },
                        evidence=[evidence],
                    ))
                    recovered.append({
                        "table_row": row_number, "sample": material.name,
                        "test_temperature": temperature, "applied_stress": stress,
                        "property": property_name, "raw_value": raw, "value": float(raw),
                        "unit": unit, "page": page_number, "table_id": table_id,
                        "locator": evidence.locator,
                    })
                experiments.append(DraftExperiment(
                    local_id=f"creep_table2_row_{row_number}", experiment_type="creep_stress_rupture",
                    material_refs=[material_id], ownership="focal_work", outputs=outputs,
                    conditions=[
                        Measurement(property="test_temperature", raw_value=f"{temperature} °C", value=temperature, unit="°C"),
                        Measurement(property="applied_stress", raw_value=f"{stress_word[4]} MPa", value=stress, unit="MPa"),
                    ],
                    evidence=[_table_evidence(page_number, table_id, row_number, "stress", stress_word)],
                ))
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], year=source_info["year"],
            authors=source_info["authors"], url=source_info["url"],
        ),
        materials=[material], processes=[process], experiments=experiments,
        domain_values={"recovery_method": "locked_pdf_creep_table2_word_geometry_v1", "table_id": table_id,
                       "omitted_NA_rows": omitted},
    )
    archive = assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery")
    return archive, recovered, omitted
