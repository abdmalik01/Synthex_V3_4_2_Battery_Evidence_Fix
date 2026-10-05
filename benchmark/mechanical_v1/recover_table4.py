"""Source-locked, value-agnostic recovery of the six Table 4 tensile rows.

The MDPI PDF's visual table is clear, but the general text-table parser fragments
headers and values. This recovery uses word coordinates and fails closed if the
expected layout or associations change. No scientific values are stored here.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

import pymupdf

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)
from synthex_platform.visual.tables import extract_tables


PROPERTIES = ("yield_strength", "ultimate_tensile_strength", "elongation")
REPORTED_TERMS = ("Yield Strength", "Ultimate Tensile Strength", "Elongation to Failure")
UNITS = ("MPa", "MPa", "%")


def _cell_words(words, left: float, right: float, y: float) -> list[tuple]:
    return sorted(
        (word for word in words if left <= word[0] < right and abs(word[1] - y) <= 3.0),
        key=lambda word: word[0],
    )


def _phrase(words) -> str:
    return " ".join(word[4] for word in words).strip()


def _header_x(words, token: str) -> float:
    matches = [word[0] for word in words if word[4] == token and 125 < word[1] < 160]
    if len(matches) != 1:
        raise ValueError(f"Table 4 header {token!r} is not uniquely positioned")
    return matches[0]


def recover_table4(pdf_path: str | Path, gold_path: str | Path):
    pdf_path = Path(pdf_path)
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    expected = gold["source"]["sha256"]
    if sha256(pdf_path.read_bytes()).hexdigest() != expected:
        raise ValueError("Mechanical source checksum does not match frozen gold")

    with pymupdf.open(pdf_path) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Mechanical source page count changed")
        matching = [
            (index, page) for index, page in enumerate(document)
            if "Table 4." in page.get_text() and "Tensile properties" in page.get_text()
        ]
        if len(matching) != 1:
            raise ValueError("The reviewed Table 4 is not uniquely identifiable")
        page_index, page = matching[0]
        if page_index + 1 != gold["gold_basis"]["page"]:
            raise ValueError("Reviewed Table 4 page changed")
        words = [word for word in page.get_text("words") if 125 < word[1] < 265]
        headers = [_header_x(words, token) for token in ("Alloy", "Heat", "Overaging", "Test", "Yield", "Ultimate", "Elongation")]
        if headers != sorted(headers):
            raise ValueError("Table 4 header order changed")
        edges = [0.0, *[(a + b) / 2 for a, b in zip(headers, headers[1:])], page.rect.width]
        test_words = sorted(
            (word for word in words if edges[3] <= word[0] < edges[4] and word[4] in {"RT", "250◦C", "250°C"}),
            key=lambda word: word[1],
        )
        if len(test_words) != 6 or [word[4] == "RT" for word in test_words] != [True, False] * 3:
            raise ValueError("Table 4 test-condition rows are ambiguous")

        table_matches = [
            item for item in extract_tables(pdf_path)
            if item.page == page_index + 1 and item.table_number == "4"
        ]
        if len(table_matches) != 1:
            raise ValueError("Table 4 stable table ID is unavailable")
        table_id = table_matches[0].table_id
        materials, processes, experiments = [], [], []
        recovered = []
        for group_index in range(3):
            pair = test_words[2 * group_index:2 * group_index + 2]
            top, bottom = pair[0][1], pair[1][1]
            group_words = [word for word in words if top - 3 <= word[1] < bottom + 10]
            sample_words = [
                word for word in group_words if edges[0] <= word[0] < edges[1]
                and top <= word[1] <= bottom + 1
            ]
            sample = _phrase(sorted(sample_words, key=lambda word: (word[1], word[0])))
            treatment_words = [
                word for word in group_words if headers[1] - 30 <= word[0] < headers[2] - 5
            ]
            treatment_text = _phrase(sorted(treatment_words, key=lambda word: (word[1], word[0])))
            if "water" in treatment_text and "aging" in treatment_text:
                treatment = "water_quench_aged"
            elif "air" in treatment_text and "cooling" in treatment_text:
                treatment = "air_cooled"
            else:
                raise ValueError(f"Table 4 heat-treatment association unclear for group {group_index}")
            if not sample:
                raise ValueError("Table 4 sample association is missing")
            material_id = f"table4_sample_{group_index + 1}"
            context_evidence = Evidence(
                page=page_index + 1, source_type="table", original_source_type="table_reported",
                verbatim_match=True, table_id=table_id, text_snippet=sample,
                locator=f"group={group_index + 1};column=alloy",
            )
            materials.append(DraftMaterial(
                local_id=material_id, name=sample, ownership="focal_work", evidence=[context_evidence],
            ))
            processes.append(DraftProcess(
                local_id=f"table4_process_{group_index + 1}", name=treatment,
                family="heat treatment", material_refs=[material_id], ownership="focal_work",
                evidence=[Evidence(
                    page=page_index + 1, source_type="table", original_source_type="table_reported",
                    verbatim_match=True, table_id=table_id,
                    text_snippet="quenching–aging" if treatment == "water_quench_aged" else "air cooling",
                    locator=f"group={group_index + 1};column=heat_treatment",
                )],
            ))
            for pair_index, test_word in enumerate(pair):
                row_index = 2 * group_index + pair_index
                y = test_word[1]
                overaging_words = [
                    word for word in words
                    if edges[2] <= word[0] < edges[3] and abs(word[1] - y) <= 5.0
                ]
                overaging_text = _phrase(sorted(overaging_words, key=lambda word: (word[1], word[0])))
                if pair_index == 0 and "No" in overaging_text:
                    overaging = "none"
                elif pair_index == 1 and "100" in overaging_text and "250" in overaging_text:
                    overaging = "100 h @ 250 °C"
                else:
                    raise ValueError(f"Table 4 overaging row {row_index + 1} is ambiguous")
                test_temperature = "RT" if test_word[4] == "RT" else 250
                outputs = []
                for col_index, (property_name, reported_term, unit) in enumerate(zip(PROPERTIES, REPORTED_TERMS, UNITS)):
                    cell = _cell_words(words, edges[4 + col_index], edges[5 + col_index], y)
                    raw = _phrase(cell)
                    match = re.fullmatch(
                        r"(\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)", raw,
                    )
                    if match is None:
                        raise ValueError(f"Table 4 result row {row_index + 1}, column {col_index + 1} is unclear: {raw!r}")
                    evidence = Evidence(
                        page=page_index + 1, source_type="table", original_source_type="table_reported",
                        verbatim_match=True, table_id=table_id, text_snippet=raw,
                        locator=(
                            f"row={row_index + 1};column={col_index + 4};"
                            f"bbox={min(word[0] for word in cell):.1f},{min(word[1] for word in cell):.1f},"
                            f"{max(word[2] for word in cell):.1f},{max(word[3] for word in cell):.1f}"
                        ),
                    )
                    outputs.append(Measurement(
                        property=property_name, raw_value=raw, value=float(match.group(1)),
                        unit=unit, uncertainty=float(match.group(2)), uncertainty_unit=unit,
                        conditions={
                            "reported_term": reported_term, "scientific_type": "reported_measurement",
                            "data_kind": "scalar", "heat_treatment": treatment,
                            "overaging": overaging, "temperature": test_temperature,
                        },
                        evidence=[evidence],
                    ))
                    recovered.append({
                        "row": row_index + 1, "sample": sample, "treatment": treatment,
                        "overaging": overaging, "test_temperature": test_temperature,
                        "property": property_name, "value": float(match.group(1)),
                        "unit": unit, "raw_value": raw, "table_id": table_id,
                        "page": page_index + 1, "locator": evidence.locator,
                    })
                experiments.append(DraftExperiment(
                    local_id=f"table4_tensile_{row_index + 1}", experiment_type="tensile_test",
                    material_refs=[material_id], ownership="focal_work", outputs=outputs,
                    conditions=[Measurement(
                        property="temperature", raw_value=test_word[4],
                        value=250 if test_temperature == 250 else None,
                        unit="°C" if test_temperature == 250 else None,
                    )],
                    evidence=[Evidence(
                        page=page_index + 1, source_type="table", original_source_type="table_reported",
                        verbatim_match=True, table_id=table_id, text_snippet=test_word[4],
                        locator=f"row={row_index + 1};column=test_condition",
                    )],
                ))
    draft = ExtractedDocument(
        source=DraftSource(
            title=gold["source"]["title"], doi=gold["source"]["doi"], year=gold["source"]["year"],
            authors=gold["source"]["authors"], url=gold["source"]["url"],
        ),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={"recovery_method": "locked_pdf_table4_word_geometry_v1", "table_id": table_id},
    )
    archive = assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery")
    return archive, recovered
