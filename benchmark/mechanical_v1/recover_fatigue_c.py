"""Source-locked recovery of actual fatigue points and censored run-outs."""

from __future__ import annotations

import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument

from .locked_case import load_locked_case


_AMPLITUDE = re.compile(r"\d+\.\d{2}\Z")
_INTEGER = re.compile(r"\d[\d,]*\Z")
_TABLES = (("A1", 13, "transverse", 32), ("A2", 14, "rolling", 28))


def _one_word(words: list[tuple], left: float, right: float, y: float) -> tuple:
    selected = [word for word in words if left < word[0] < right and abs(word[1] - y) < 1.8]
    if len(selected) != 1:
        raise ValueError(f"Fatigue table cell ambiguous at y={y:.1f}, x={left:.1f}-{right:.1f}")
    return selected[0]


def _evidence(page: int, table_id: str, row: int, column: str, word: tuple) -> Evidence:
    return Evidence(
        page=page, source_type="table", original_source_type="table_reported",
        verbatim_match=True, table_id=table_id, text_snippet=word[4],
        locator=(
            f"row={row};column={column};"
            f"bbox={word[0]:.1f},{word[1]:.1f},{word[2]:.1f},{word[3]:.1f}"
        ),
    )


def recover_fatigue_c():
    source, gold, lock = load_locked_case("MECH-FATIGUE-C")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Fatigue PDF page count differs from source lock")
        if "A37JC steel" not in document[2].get_text():
            raise ValueError("Fatigue sample identity is missing from the primary source")
        if not re.search(r"R\s*=\s*[−-]1", document[5].get_text()):
            raise ValueError("Fatigue R = -1 is not supported by the source")
        experiments = []
        recovered = []
        table_ids = {}
        for table_label, page_number, orientation, expected_rows in _TABLES:
            page = document[page_number - 1]
            text = page.get_text()
            if f"Table {table_label}." not in text or "constant amplitude loading" not in text:
                raise ValueError(f"Reviewed Table {table_label} caption is missing")
            if "Run-out: Stopped at" not in text or "cycles without failure" not in text:
                raise ValueError(f"Table {table_label} run-out footnote is missing")
            words = page.get_text("words")
            caption_words = [word for word in words if word[4] == table_label + "."]
            if len(caption_words) != 1:
                raise ValueError(f"Table {table_label} caption is not unique")
            caption_y = caption_words[0][1]
            footers = [word for word in words if word[4] == "Run-out:" and word[1] > caption_y]
            if not footers:
                raise ValueError(f"Table {table_label} bounds cannot be identified")
            footer_y = min(word[1] for word in footers)
            headers = [word for word in words if (
                word[4] == "Stress" and 175 < word[0] < 210
                and caption_y < word[1] < footer_y
            )]
            if len(headers) != 1:
                raise ValueError(f"Table {table_label} bounds cannot be identified")
            header_y = headers[0][1]
            amplitude_words = sorted(
                (word for word in words if 200 < word[0] < 300
                 and header_y + 5 < word[1] < footer_y - 5
                 and _AMPLITUDE.fullmatch(word[4])), key=lambda word: word[1],
            )
            if len(amplitude_words) != expected_rows:
                raise ValueError(f"Table {table_label} row count changed")
            table_id = stable_id("tbl", lock["source_sha256"], table_label, page_number)
            table_ids[table_label] = table_id
            for row_number, amplitude_word in enumerate(amplitude_words, 1):
                y = amplitude_word[1]
                cycles_word = _one_word(words, 320, 440, y)
                frequency_word = _one_word(words, 450, 550, y)
                amplitude_raw = amplitude_word[4]
                cycles_raw = cycles_word[4]
                frequency_raw = frequency_word[4]
                if not _INTEGER.fullmatch(frequency_raw):
                    raise ValueError(f"Table {table_label} row {row_number} frequency unclear")
                if cycles_raw == "Run-out":
                    outcome, cycles = "runout", None
                elif _INTEGER.fullmatch(cycles_raw):
                    outcome, cycles = "failure", int(cycles_raw.replace(",", ""))
                else:
                    raise ValueError(f"Table {table_label} row {row_number} fatigue outcome unclear")
                frequency = int(frequency_raw)
                amplitude = float(amplitude_raw)
                conditions = {
                    "processing_state": "not_reported", "orientation": orientation,
                    "loading_mode": "rotating_bending", "stress_ratio": -1,
                    "test_frequency_rpm": frequency, "failure_or_runout": outcome,
                    "scientific_type": "reported_measurement",
                    "data_kind": "series_point" if outcome == "failure" else "scalar",
                    "curve_role": "curve_point" if outcome == "failure" else "scalar",
                }
                if outcome == "failure":
                    conditions.update({
                        "series_origin": "source_table", "series_id": f"Table {table_label}",
                        "cycles_to_failure": cycles, "stress_amplitude": amplitude,
                    })
                else:
                    conditions["runout_limit_cycles"] = 10000000
                amplitude_evidence = _evidence(page_number, table_id, row_number, "stress_amplitude", amplitude_word)
                outputs = [Measurement(
                    property="stress_amplitude", raw_value=amplitude_raw,
                    value=amplitude, unit="MPa", method="rotating bending",
                    conditions={**conditions, "reported_term": "Stress Amplitude"},
                    evidence=[amplitude_evidence],
                )]
                if outcome == "failure":
                    outputs.append(Measurement(
                        property="cycles_to_failure", raw_value=cycles_raw,
                        value=cycles, unit="cycles", method="rotating bending",
                        conditions={**conditions, "reported_term": "Cycles to Failure"},
                        evidence=[_evidence(page_number, table_id, row_number, "cycles_to_failure", cycles_word)],
                    ))
                experiments.append(DraftExperiment(
                    local_id=f"fatigue_{table_label}_row_{row_number}",
                    experiment_type="rotating_bending_fatigue",
                    material_refs=["fatigue_a37jc_steel"], ownership="focal_work",
                    conditions=[
                        Measurement(property="stress_ratio", raw_value="R = −1", value=-1, unit="1"),
                        Measurement(property="test_frequency", raw_value=f"{frequency_raw} RPM", value=frequency, unit="RPM"),
                    ],
                    outputs=outputs,
                    evidence=[amplitude_evidence, _evidence(page_number, table_id, row_number, "test_frequency", frequency_word)],
                ))
                recovered.append({
                    "table": table_label, "table_row": row_number, "page": page_number,
                    "orientation": orientation, "stress_amplitude": amplitude,
                    "raw_stress_amplitude": amplitude_raw,
                    "cycles_to_failure": cycles, "raw_cycles": cycles_raw,
                    "outcome": outcome, "test_frequency_rpm": frequency,
                    "table_id": table_id, "locator": amplitude_evidence.locator,
                })
    source_info = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=source_info["title"], doi=source_info["doi"], year=source_info["year"],
            authors=source_info["authors"], url=source_info["url"],
        ),
        materials=[DraftMaterial(
            local_id="fatigue_a37jc_steel", name="A37JC steel", ownership="focal_work",
            evidence=[Evidence(
                page=3, source_type="text", original_source_type="native_text",
                verbatim_match=True, text_snippet="A37JC steel",
            )],
        )],
        experiments=experiments,
        domain_values={"recovery_method": "locked_pdf_fatigue_appendix_word_geometry_v1",
                       "table_ids": table_ids},
    )
    archive = assemble_archive(draft, domain="mechanical", model="deterministic_table_recovery")
    return archive, recovered
