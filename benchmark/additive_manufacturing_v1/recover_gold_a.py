"""Deterministic word-geometry recovery for AM-GOLD-A Table 1."""

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
    DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)


CASE_DIR = Path(__file__).resolve().parent
_SAMPLE = re.compile(r"T(\d+)\Z")
_COLUMN_WINDOWS = {
    "left": ((95, 135), (140, 195), (195, 245), (245, 295)),
    "right": ((350, 400), (400, 460), (455, 510), (510, 555)),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell_word(words: list[tuple], y: float, left: float, right: float) -> tuple:
    selected = [word for word in words if left < word[0] < right and abs(word[1] - y) < 1.0]
    if len(selected) != 1:
        raise ValueError(f"Ambiguous AM-GOLD-A cell at y={y:.1f}, x={left}-{right}")
    return selected[0]


def _table_evidence(table_id: str, sample: str, column: str, word: tuple) -> Evidence:
    return Evidence(
        page=4, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=word[4],
        locator=(
            f"row={sample};column={column};"
            f"bbox={word[0]:.1f},{word[1]:.1f},{word[2]:.1f},{word[3]:.1f}"
        ),
    )


def _text_evidence(page: int, snippet: str, section: str) -> Evidence:
    return Evidence(
        page=page, section=section, source_type="text", original_source_type="native_text",
        verbatim_match=True, text_snippet=snippet, locator=f"page={page};section={section}",
    )


def _measurement(
    property_name: str, raw: str, value, unit: str | None, evidence: Evidence,
    *, scientific_type: str = "reported_process_parameter", qualifier: str = "exact",
) -> Measurement:
    return Measurement(
        property=property_name, raw_value=raw, value=value, unit=unit,
        qualifier=qualifier,
        conditions={"scientific_type": scientific_type, "data_kind": "scalar"},
        evidence=[evidence],
    )


def _extract_rows(page, table_id: str) -> list[dict]:
    words = page.get_text("words")
    rows = []
    for sample_word in words:
        match = _SAMPLE.fullmatch(sample_word[4])
        if not match or not (130 < sample_word[1] < 290):
            continue
        side = "left" if sample_word[0] < 100 else "right"
        cells = [
            _cell_word(words, sample_word[1], left, right)
            for left, right in _COLUMN_WINDOWS[side]
        ]
        sample = sample_word[4]
        rows.append({
            "sample": sample,
            "sample_number": int(match.group(1)),
            "sample_evidence": _table_evidence(table_id, sample, "sample", sample_word),
            "laser_power_w": float(cells[0][4]),
            "laser_power_raw": cells[0][4],
            "laser_power_evidence": _table_evidence(table_id, sample, "LP/(W)", cells[0]),
            "scan_speed_mm_s": float(cells[1][4]),
            "scan_speed_raw": cells[1][4],
            "scan_speed_evidence": _table_evidence(table_id, sample, "SS/(mm/s)", cells[1]),
            "hatch_spacing_mm": float(cells[2][4]),
            "hatch_spacing_raw": cells[2][4],
            "hatch_spacing_evidence": _table_evidence(table_id, sample, "HS/(mm)", cells[2]),
            "relative_density_pct": float(cells[3][4]),
            "relative_density_raw": cells[3][4],
            "relative_density_evidence": _table_evidence(table_id, sample, "RD/(%)", cells[3]),
        })
    rows.sort(key=lambda item: item["sample_number"])
    if [item["sample_number"] for item in rows] != list(range(1, 28)):
        raise ValueError("AM-GOLD-A Table 1 specimen sequence is incomplete or ambiguous")
    return rows


def recover_gold_a():
    lock = _read(CASE_DIR / "source_lock.json")
    gold = _read(CASE_DIR / lock["gold_file"])
    source = CASE_DIR / lock["source_file"]
    if _sha256(source) != lock["source_sha256"]:
        raise ValueError("AM-GOLD-A source checksum differs from the source lock")
    if _sha256(CASE_DIR / lock["gold_file"]) != lock["gold_sha256"]:
        raise ValueError("AM-GOLD-A gold checksum differs from the source lock")

    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("AM-GOLD-A PDF page count differs from the source lock")
        feedstock_text = document[1].get_text().replace("ﬁ", "fi")
        method_text = document[2].get_text().replace("ﬁ", "fi")
        normalized_method_text = re.sub(r"\s+", " ", method_text)
        table_page = document[3]
        table_text = table_page.get_text().replace("ﬁ", "fi")
        if not all(term in feedstock_text for term in ("D10 = 10", "D50 = 15.87", "D90 = 24.86")):
            raise ValueError("AM-GOLD-A feedstock particle-size statement changed")
        if not all(term in normalized_method_text for term in (
            "SLM 280HL", "high-purity argon", "300 ppm", "423.15 K", "0.03 mm",
            "zigzag scanning strategy", "67",
        )):
            raise ValueError("AM-GOLD-A shared build context changed")
        if "Table 1. The process parameters used in this work and measured relative density." not in table_text:
            raise ValueError("AM-GOLD-A Table 1 caption changed")
        if not all(term in table_text for term in (
            "wire electrical discharge", "ultrasonic cleaning", "Archimedes method",
            "measured results three times",
        )):
            raise ValueError("AM-GOLD-A characterization/post-processing context changed")
        table_id = stable_id("tbl", lock["source_sha256"], "Table 1", 4)
        rows = _extract_rows(table_page, table_id)

    recovered_values = [{key: row[key] for key in (
        "sample", "laser_power_w", "scan_speed_mm_s", "hatch_spacing_mm",
        "relative_density_pct",
    )} for row in rows]
    if recovered_values != gold["rows"]:
        raise ValueError("AM-GOLD-A recovered Table 1 values differ from frozen gold")

    feedstock_evidence = _text_evidence(
        2, "D10 = 10 µm, D50 = 15.87 µm, and D90 = 24.86 µm",
        "2.1. Tungsten Powder Feedstock",
    )
    shared_evidence = {
        "machine_model": _text_evidence(3, "SLM 280HL", "2.2. Experimental Methods and Parameters"),
        "shielding_gas": _text_evidence(3, "high-purity argon", "2.2. Experimental Methods and Parameters"),
        "chamber_oxygen": _text_evidence(3, "below 300 ppm", "2.2. Experimental Methods and Parameters"),
        "preheat_temperature": _text_evidence(3, "423.15 K", "2.2. Experimental Methods and Parameters"),
        "layer_thickness": _text_evidence(3, "0.03 mm", "2.2. Experimental Methods and Parameters"),
        "scan_strategy": _text_evidence(3, "zigzag scanning strategy", "2.2. Experimental Methods and Parameters"),
        "rotation_angle": _text_evidence(3, "67◦", "2.2. Experimental Methods and Parameters"),
    }
    post_evidence = _text_evidence(
        4, "All tungsten samples were removed from the substrate via wire electrical discharge machining. Subsequently, the samples were cleaned using an ultrasonic cleaning machine and then dried.",
        "2.3. Materials Characterization",
    )

    materials = [DraftMaterial(
        local_id="feedstock_w", name="pure tungsten powder", formula="W",
        morphology={
            "shape": "spherical", "particle_size_d10_um": 10.0,
            "particle_size_d50_um": 15.87, "particle_size_d90_um": 24.86,
        },
        tags=["am_feedstock", "powder", "ownership:focal_work"],
        ownership="focal_work", evidence=[feedstock_evidence],
    )]
    processes = []
    experiments = []
    for row in rows:
        sample = row["sample"]
        material_id = f"specimen_{sample.lower()}"
        materials.append(DraftMaterial(
            local_id=material_id, name=f"{sample} as-built tungsten specimen", formula="W",
            tags=["am_part", "as_built", f"source_sample:{sample}", "ownership:focal_work"],
            ownership="focal_work", evidence=[row["sample_evidence"]],
        ))
        parameters = [
            _measurement("laser_power", row["laser_power_raw"], row["laser_power_w"], "W", row["laser_power_evidence"]),
            _measurement("scan_speed", row["scan_speed_raw"], row["scan_speed_mm_s"], "mm/s", row["scan_speed_evidence"]),
            _measurement("hatch_spacing", row["hatch_spacing_raw"], row["hatch_spacing_mm"], "mm", row["hatch_spacing_evidence"]),
            _measurement("layer_thickness", "0.03 mm", 0.03, "mm", shared_evidence["layer_thickness"]),
            _measurement("scan_strategy", "zigzag", "zigzag", None, shared_evidence["scan_strategy"]),
            _measurement("rotation_angle", "67◦", 67.0, "°", shared_evidence["rotation_angle"]),
            _measurement("shielding_gas", "high-purity argon", "high-purity argon", None, shared_evidence["shielding_gas"]),
            _measurement("chamber_oxygen", "below 300 ppm", 300.0, "ppm", shared_evidence["chamber_oxygen"], qualifier="upper_bound"),
            _measurement("preheat_temperature", "423.15 K", 423.15, "K", shared_evidence["preheat_temperature"]),
            _measurement("machine_model", "SLM 280HL", "SLM 280HL", None, shared_evidence["machine_model"]),
        ]
        processes.extend([
            DraftProcess(
                local_id=f"build_{sample.lower()}", name=f"LPBF build {sample}",
                family="laser_powder_bed_fusion", input_material_refs=["feedstock_w"],
                output_material_refs=[material_id], parameters=parameters,
                atmosphere="high-purity argon; oxygen below 300 ppm", equipment="SLM 280HL",
                ownership="focal_work", evidence=[row["sample_evidence"]],
            ),
            DraftProcess(
                local_id=f"post_{sample.lower()}",
                name="wire EDM removal, ultrasonic cleaning, and drying",
                family="post_processing", input_material_refs=[material_id],
                output_material_refs=[material_id], ownership="focal_work",
                evidence=[post_evidence],
            ),
        ])
        output = _measurement(
            "relative_density", row["relative_density_raw"], row["relative_density_pct"], "%",
            row["relative_density_evidence"], scientific_type="reported_measurement",
        )
        output.method = "Archimedes method; average of three measurements"
        output.conditions.update({"reported_term": "RD", "replicates": 3})
        experiments.append(DraftExperiment(
            local_id=f"density_{sample.lower()}", experiment_type="relative_density_measurement",
            material_refs=[material_id], target="densification", outputs=[output],
            protocol="Archimedes method; three measurements", ownership="focal_work",
            evidence=[row["relative_density_evidence"]],
        ))

    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], url=source_info["url"],
            year=source_info["year"], authors=source_info["authors"],
        ),
        materials=materials, processes=processes, experiments=experiments,
        domain_values={
            "paper_types": ["feedstock_characterization", "laser_powder_bed_fusion", "quality_characterization"],
            "recovery_method": "locked_pdf_table1_word_geometry_v1",
            "source_checksum": lock["source_sha256"], "table_id": table_id,
            "provider_invoked": False,
        },
    )
    archive = assemble_archive(
        draft, domain="additive_manufacturing", model="deterministic_table_recovery"
    )
    return archive, recovered_values
