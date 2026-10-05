"""Extract exact published table cells from locked publisher PDFs, without gold input."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent


def resolve_run_artifact_root(value: str) -> Path:
    """Resolve a portable, repository-relative provider artifact reference."""
    repository = ROOT.parents[1].resolve()
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or ":" in value or "\\" in value:
        raise ValueError("Provider artifact path must be repository-relative")
    resolved = (repository / relative).resolve()
    if not resolved.is_relative_to(repository):
        raise ValueError("Provider artifact path escapes repository")
    return resolved
LOCK_NAMES = {
    "SEM-GOLD-A": "source_lock_a.json",
    "SEM-TRANSPORT-B": "source_lock_transport_b.json",
    "SEM-OPTICAL-C": "source_lock_optical_c.json",
    "SEM-PROCESS-D": "source_lock_process_d.json",
    "SEM-COMPUTE-E": "source_lock_compute_e.json",
    "SEM-REVIEW-F": "source_lock_review_f.json",
    "SEM-NEG-G": "source_lock_neg_g.json",
    "SEM-MIXED-H": "source_lock_mixed_h.json",
}
_CELL = re.compile(r"\d+(?:\.\d+)?(?:\s*×\s*10\s*[−-]?\s*\d{1,2})?|-+")


def source_lock(case_id: str) -> dict:
    lock = json.loads((ROOT / LOCK_NAMES[case_id]).read_text(encoding="utf-8"))
    pdf = ROOT / lock["article_file"]
    gold = ROOT / lock["gold_file"]
    for path, expected in ((pdf, lock["article_sha256"]), (gold, lock["gold_sha256"])):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"SEM source/gold lock mismatch: {case_id} {path.name}")
    return lock


def page_text(case_id: str, page: int) -> str:
    lock = source_lock(case_id)
    reader = PdfReader(str(ROOT / lock["article_file"]))
    if len(reader.pages) != lock["article_page_count"]:
        raise ValueError(f"SEM page-count mismatch: {case_id}")
    return reader.pages[page - 1].extract_text() or ""


def _number(raw: str) -> float | None:
    if set(raw.strip()) == {"-"}:
        return None
    normalized = raw.replace("−", "-")
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:\s*×\s*10\s*(-?\s*\d{1,2}))?\s*", normalized)
    if not match:
        raise ValueError(f"Unrecognized PDF numeric cell: {raw!r}")
    return float(match[1]) * 10 ** (int(match[2].replace(" ", "")) if match[2] else 0)


def gold_a_rows() -> list[dict]:
    text = page_text("SEM-GOLD-A", 4)
    if "Table 2." not in text or "n/×1020" not in text:
        raise ValueError("SEM-GOLD-A Table 2 header missing")
    rows = []
    pattern = re.compile(r"^(ZnO|Zn\d+(?:\.\d+)?Ga\d+(?:\.\d+)?O)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)$", re.MULTILINE)
    for match in pattern.finditer(text):
        raw = match.group(0)
        film = match[1]
        ga = float(re.search(r"Ga(\d+(?:\.\d+)?)", film)[1]) * 100 if "Ga" in film else 0.0
        rows.append({
            "film": film, "ga_atomic_percent": ga,
            "thickness_nm": int(match[2]), "carrier_concentration_scaled": float(match[3]),
            "hall_mobility": float(match[4]), "resistivity_scaled": float(match[5]),
            "sheet_resistance": float(match[6]), "optical_band_gap": float(match[9]),
            "raw_cells": {"thickness_nm": match[2], "carrier_concentration_scaled": match[3],
                          "hall_mobility": match[4], "resistivity_scaled": match[5],
                          "sheet_resistance": match[6], "optical_band_gap": match[9]},
            "source_line": raw,
        })
    if len(rows) != 4:
        raise ValueError(f"SEM-GOLD-A expected four table rows, got {len(rows)}")
    return rows


def transport_b_rows() -> list[dict]:
    text = page_text("SEM-TRANSPORT-B", 8)
    if "Table 2 Resistivity" not in text:
        raise ValueError("SEM-TRANSPORT-B Table 2 missing")
    table = text.split("Table 2 Resistivity", 1)[1].split("Wang et al.", 1)[0]
    groups = (table.split("As-grown Annealed in air", 1)[1].split("Annealed in Ar", 1)[0],
              table.split("Annealed in Ar Annealed in N 2", 1)[1])
    result = []
    for group_no, group in enumerate(groups):
        for line in group.splitlines():
            match = re.match(r"^([0-4])\s+(.+)$", line.strip())
            if not match:
                continue
            cells = [item.group() for item in _CELL.finditer(match[2])]
            if len(cells) == 5 and cells[-1] == "--":
                cells[-1:] = ["-", "-"]
            if len(cells) != 6:
                raise ValueError(f"SEM-TRANSPORT-B ambiguous table row: {line!r}: {cells!r}")
            for side in (0, 1):
                state = (("as_grown", "annealed_air") if group_no == 0 else ("annealed_ar", "annealed_n2"))[side]
                names = ("resistivity", "carrier_concentration", "carrier_mobility")
                raw_cells = dict(zip(names, cells[side * 3:side * 3 + 3]))
                result.append({
                    "al_atomic_percent": int(match[1]), "state": state,
                    **{name: _number(raw_cells[name]) for name in names},
                    "raw_cells": raw_cells, "source_line": line.strip(),
                })
    order = {"as_grown": 0, "annealed_air": 1, "annealed_ar": 2, "annealed_n2": 3}
    result.sort(key=lambda row: (order[row["state"]], row["al_atomic_percent"]))
    if len(result) != 20:
        raise ValueError(f"SEM-TRANSPORT-B expected 20 table specimens, got {len(result)}")
    return result


def optical_c_rows() -> tuple[list[dict], list[dict], dict[tuple[str, str], dict]]:
    context = page_text("SEM-OPTICAL-C", 3)
    absorption = page_text("SEM-OPTICAL-C", 6)
    pl = page_text("SEM-OPTICAL-C", 8)
    if not all(term in context + absorption + pl for term in ("Table 1.", "Table 2.", "Table 3.")):
        raise ValueError("SEM-OPTICAL-C source tables missing")
    films: dict[tuple[str, str], dict] = {}
    substrate = None
    sample = None
    context_table = context.split("Sample Substrate P Al", 1)[1].split("1 Standard error", 1)[0]
    for line in context_table.splitlines():
        stripped = line.strip()
        if stripped == "M1":
            sample = stripped
            continue
        if stripped in {"Si(100)", "Si(111)"}:
            substrate = stripped
            continue
        match = re.match(r"^(?:(M[1-5])\s+)?(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+([\d.]+)$", stripped)
        if match and substrate and (match[1] or sample):
            sample = match[1] or sample
            films[(sample, substrate)] = {"al_mole_fraction": float(match[4]), "thickness_nm": int(match[6]), "source_line": stripped}
    # PDF extraction places the substrate label on its own line before each five-row block.
    if len(films) != 10:
        raise ValueError(f"SEM-OPTICAL-C Table 1 expected ten films, got {len(films)}")
    absorb_rows = []
    for match in re.finditer(r"^(M[1-5])\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)$", absorption, re.MULTILINE):
        absorb_rows.append({"sample": match[1], "al_mole_fraction": float(match[2]),
                            "substrate": "sapphire", "measurement_temperature": "room_temperature",
                            "apparent_optical_band_gap_ev": float(match[4]),
                            "raw_cell": match[4], "source_line": match[0]})
    if len(absorb_rows) != 5:
        raise ValueError(f"SEM-OPTICAL-C Table 2 expected five rows, got {len(absorb_rows)}")
    pl_rows = []
    block = pl.split("Table 3.", 1)[1].split("1 Standard error", 1)[0]
    sample = None
    temperature = None
    for line in block.splitlines():
        stripped = line.strip()
        if stripped in {"M1", "M2"}:
            sample = stripped
            continue
        match = re.match(r"^(?:(11|300)\s+)?(Si\(100\)|Si\(111\))\s+([\d.]+)\s+(\d+)\s+(\d+)$", stripped)
        if match and sample:
            if match[1]:
                temperature = int(match[1])
            film = films[(sample, match[2])]
            pl_rows.append({"sample": sample, "substrate": match[2],
                            "al_mole_fraction": film["al_mole_fraction"],
                            "thickness_nm": film["thickness_nm"],
                            "measurement_temperature_k": temperature,
                            "pl_peak_ev": float(match[3]), "raw_cell": match[3],
                            "source_line": stripped})
    if len(pl_rows) != 8:
        raise ValueError(f"SEM-OPTICAL-C Table 3 expected eight PL rows, got {len(pl_rows)}")
    return absorb_rows, pl_rows, films


def process_d_rows() -> list[dict]:
    text = page_text("SEM-PROCESS-D", 2)
    if "Table 1." not in text or "Hall coefficient" not in text:
        raise ValueError("SEM-PROCESS-D Table 1 missing")
    found = []
    pattern = re.compile(r"^(?:(\d{3})\s*°C\s+)?(?:(\d{3})\s*s\s+)?(\d{2}\.\d{3})\s+(\d{2}\.\d{2})\s+(−\s*\d+\.\d+)\s+([\d.]+)\s+[\d.]+%\s+[\d.]+$", re.MULTILINE)
    for match in pattern.finditer(text):
        found.append({"temperature_cell": match[1], "time_cell": match[2],
                      "crystallite_size_nm": float(match[4]), "hall_coefficient_scaled": -float(match[5].replace("−", "").strip()),
                      "raw_cells": {"crystallite_size_nm": match[4], "hall_coefficient_scaled": match[5]},
                      "source_line": match[0]})
    if len(found) != 10 or found[2]["time_cell"] != "220" or found[7]["temperature_cell"] != "700":
        raise ValueError("SEM-PROCESS-D merged-cell group anchors not found")
    for index, row in enumerate(found):
        row["series"] = "temperature_at_220_s" if index < 5 else "time_at_700_c"
        row["tempering_temperature_c"] = int(row["temperature_cell"] or ("700" if index >= 5 else "")) if index >= 5 or row["temperature_cell"] else None
        row["tempering_time_s"] = 220 if index < 5 else int(row["time_cell"] or "220")
        if row["tempering_temperature_c"] is None:
            raise ValueError("SEM-PROCESS-D temperature cell missing")
    return found
