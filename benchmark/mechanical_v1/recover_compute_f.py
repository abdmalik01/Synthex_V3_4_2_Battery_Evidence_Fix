"""Source-locked word-geometry recovery for MECH-COMPUTE-F Tables 2 and 3."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation, DraftMaterial, DraftSource, ExtractedDocument,
)

from .locked_case import load_locked_case


_NUMBER = re.compile(r"\d+(?:\.\d+)?\Z")
_ROWS = (
    ("AuIn2", "AuIn2", "AuIn2"),
    ("Sc-S_Au", "Sc−SAu", "Sc−SAu"),
    ("Y-S_Au", "Y−Su", "Y−SAu"),
    ("Y-S_In", "Y−SIn", "Y−SIn"),
)
_TABLE2_COLUMNS = (
    ("elastic_constant_c11", "C11", 230, 285),
    ("elastic_constant_c12", "C12", 285, 335),
    ("elastic_constant_c44", "C44", 335, 385),
)
_TABLE3_COLUMNS = (
    ("bulk_modulus", "B", 215, 255),
    ("shear_modulus", "G_H", 340, 385),
    ("youngs_modulus", "E", 385, 430),
    ("poisson_ratio", "ν", 525, 565),
)


def _word(words: list[tuple], token: str, y_min: float, y_max: float) -> tuple:
    matches = [item for item in words if item[4] == token and y_min < item[1] < y_max]
    if len(matches) != 1:
        raise ValueError(f"Compute table row label {token!r} is ambiguous")
    return matches[0]


def _value_word(words: list[tuple], left: float, right: float, y: float) -> tuple:
    matches = [
        item for item in words if left <= item[0] < right and abs(item[1] - y) < 1.2
        and _NUMBER.fullmatch(item[4])
    ]
    if len(matches) != 1:
        raise ValueError(f"Compute table cell is ambiguous at y={y:.1f}, x={left}-{right}")
    return matches[0]


def _evidence(page: int, table_id: str, row: int, column: str, word: tuple) -> Evidence:
    return Evidence(
        page=page, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=word[4],
        locator=(f"row={row};column={column};"
                 f"bbox={word[0]:.1f},{word[1]:.1f},{word[2]:.1f},{word[3]:.1f}"),
    )


def recover_compute_f():
    source, gold, lock = load_locked_case("MECH-COMPUTE-F")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Compute PDF page count differs from source lock")
        method_text = document[1].get_text().replace("−", "-")
        required_method = ("CASTEP code", "local density approximation", "Ultrasoft", "2×2×2", "360 eV")
        if not all(term in method_text for term in required_method):
            raise ValueError("Compute method context changed")
        page2 = document[2]
        page3 = document[4]
        if "Table 2. The calculated elastic constants" not in page2.get_text():
            raise ValueError("Compute Table 2 caption missing")
        if "Table 3. The calculated bulk modulus" not in page3.get_text():
            raise ValueError("Compute Table 3 caption missing")
        words2 = page2.get_text("words")
        words3 = page3.get_text("words")
        table2_id = stable_id("tbl", lock["source_sha256"], "Table 2", 3)
        table3_id = stable_id("tbl", lock["source_sha256"], "Table 3", 5)
        outputs_by_material: dict[str, list[Measurement]] = {name: [] for name, _, _ in _ROWS}
        recovered = []
        material_evidence = {}
        for row_number, (material, raw2, raw3) in enumerate(_ROWS, 1):
            label2 = _word(words2, raw2, 685, 740)
            label3 = _word(words3, raw3, 195, 250)
            material_evidence[material] = Evidence(
                page=3, source_type="table", original_source_type="table_reported",
                verbatim_match=True, table_id=table2_id, text_snippet=raw2,
                locator=(f"row={row_number};column=phase;"
                         f"bbox={label2[0]:.1f},{label2[1]:.1f},{label2[2]:.1f},{label2[3]:.1f}"),
            )
            for table, page, words, label, table_id, columns in (
                (2, 3, words2, label2, table2_id, _TABLE2_COLUMNS),
                (3, 5, words3, label3, table3_id, _TABLE3_COLUMNS),
            ):
                for property_name, reported_term, left, right in columns:
                    value_word = _value_word(words, left, right, label[1])
                    unit = "dimensionless" if property_name == "poisson_ratio" else "GPa"
                    evidence = _evidence(page, table_id, row_number, reported_term, value_word)
                    output = Measurement(
                        property=property_name, raw_value=value_word[4], value=float(value_word[4]), unit=unit,
                        method="CASTEP DFT; CA-PZ LDA; USPP",
                        conditions={
                            "scientific_type": "simulation_result", "reported_term": reported_term,
                            "data_kind": "scalar", "curve_role": "scalar", "phase": material,
                            "calculation_method": "density functional theory",
                        },
                        evidence=[evidence],
                    )
                    outputs_by_material[material].append(output)
                    recovered.append({
                        "table": table, "table_row": row_number, "page": page,
                        "material": material, "raw_material": raw2 if table == 2 else raw3,
                        "property": property_name, "reported_term": reported_term,
                        "raw_value": value_word[4], "value": float(value_word[4]), "unit": unit,
                        "table_id": table_id, "locator": evidence.locator,
                    })
    source_info = gold["source"]
    method = gold["gold_basis"]["method"]
    materials = [DraftMaterial(
        local_id=f"compute_{material.lower()}", name=material, ownership="focal_work",
        tags=["AuIn2", "computed_phase", material], evidence=[material_evidence[material]],
    ) for material, _, _ in _ROWS]
    calculations = []
    for material, _, _ in _ROWS:
        outputs = outputs_by_material[material]
        calculations.append(DraftCalculation(
            local_id=f"compute_elasticity_{material.lower()}",
            calculation_type=method["calculation_type"],
            material_refs=[f"compute_{material.lower()}"], ownership="focal_work",
            code=method["software"], method=method["theory"], functional=method["functional"],
            model={
                "pseudopotential": method["pseudopotential"], "optimizer": method["optimizer"],
                "supercell": method["supercell"], "doping_concentration_percent": method["doping_concentration_percent"],
                "k_point_grid": method["k_point_grid"], "cutoff_energy_ev": method["cutoff_energy_ev"],
                "total_energy_convergence_ev_per_atom": method["total_energy_convergence_ev_per_atom"],
                "maximum_stress_gpa": method["maximum_stress_gpa"],
                "maximum_force_ev_per_angstrom": method["maximum_force_ev_per_angstrom"],
            },
            outputs=outputs, evidence=[outputs[0].evidence[0]],
        ))
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], year=source_info["year"],
            authors=source_info["authors"], url=source_info["url"],
        ),
        materials=materials, calculations=calculations,
        domain_values={
            "recovery_method": "locked_pdf_compute_tables2_3_word_geometry_v1",
            "table_ids": [table2_id, table3_id], "purely_computational": True,
        },
    )
    return assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery"), recovered
