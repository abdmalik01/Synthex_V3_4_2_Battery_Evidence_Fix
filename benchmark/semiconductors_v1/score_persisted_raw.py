"""Conservative source-gold scoring of immutable raw Semiconductor payloads.

This reads the original provider JSON, never the repaired candidate. Scientific
value recovery does not imply a valid archive or canonical admission.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from synthex_platform.benchmarks.provider_artifacts import _io_path
from synthex_platform.extraction.semiconductors_contract import _unit_key

from .source_tables import ROOT, source_lock


_A_PROPERTIES = {
    "carrier_concentration": ("carrier_concentration", "electron_concentration"),
    "hall_mobility": ("hall_mobility", "carrier_mobility"),
    "resistivity": ("resistivity",),
    "sheet_resistance": ("sheet_resistance",),
    "optical_band_gap": ("optical_band_gap",),
}
_B_PROPERTIES = {
    "resistivity": ("resistivity",),
    "carrier_concentration": ("carrier_concentration", "electron_concentration"),
    "carrier_mobility": ("carrier_mobility",),
}
_EXPECTED_UNITS = {
    "carrier_concentration": {"cm-3", "x1020cm-3"},
    "hall_mobility": {"cm2/v/s", "cm2/vs"},
    "carrier_mobility": {"cm2/v/s", "cm2/vs"},
    "resistivity": {"ohmcm", "x10-3ohmcm"},
    "sheet_resistance": {"ohm/sq", "ohm/square"},
    "optical_band_gap": {"ev"},
}
_NUMBER = re.compile(r"^\s*([+\-−]?\d+(?:\.\d+)?)\s*(?:[×x*]\s*10\s*\^?\s*([+\-−]?\d+))?\s*$")


def _number(raw: object) -> float | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if not isinstance(raw, str):
        return None
    match = _NUMBER.fullmatch(raw)
    if not match:
        return None
    base = float(match[1].replace("−", "-"))
    exponent_text = match[2].replace("−", "-") if match[2] else "0"
    # PDF text extraction can flatten 10^19 into 1019, as in B Table 2.
    if "^" not in raw and exponent_text.startswith("10") and len(exponent_text) == 4:
        exponent_text = exponent_text[2:]
    exponent = int(exponent_text)
    return base * 10**exponent


def _physical_value(item: dict) -> float | None:
    # Validate provider-normalized numbers against the independently parsed raw
    # value and its displayed scale, rather than trusting a convenient number.
    value = _number(item.get("raw_value", item.get("value")))
    if value is None:
        return None
    unit = _unit_key(item.get("unit"))
    if unit == "x1020cm-3":
        value *= 1e20
    elif unit == "x10-3ohmcm":
        value *= 1e-3
    for key in ("normalized_value", "parsed_value"):
        declared = item.get(key)
        if declared is not None and (
            not isinstance(declared, (int, float)) or isinstance(declared, bool)
            or not math.isfinite(declared)
            or not math.isclose(float(declared), value, rel_tol=1e-7, abs_tol=1e-12)
        ):
            return None
    return value


def _records(raw: dict) -> list[dict]:
    for key in ("derived_properties", "measurements", "properties"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _property(item: dict) -> str | None:
    return item.get("property") or item.get("property_key") or item.get("canonical_key")


def _a_sample(item: dict, materials: dict[str, dict]) -> str | None:
    material = materials.get(str(item.get("material_ref")), {})
    return material.get("formula") or material.get("chemical_formula") or material.get("composition_formula")


def _b_sample(item: dict, materials: dict[str, dict]) -> tuple[int, str] | None:
    conditions = item.get("conditions") or {}
    if not isinstance(conditions, dict):
        conditions = {}
    material = materials.get(str(item.get("material_ref")), {})
    text = " ".join(str(value) for value in (
        conditions.get("sample", ""), conditions.get("sample_label", ""),
        conditions.get("processing_state", ""), material.get("name", ""),
        material.get("description", ""),
    )).casefold()
    match = re.search(r"(\d+(?:\.\d+)?)\s*at\.?\s*%\s*(?:al)?", text)
    percent = int(float(match[1])) if match else 0 if "undoped" in text or "0 at" in text else None
    if percent is None:
        return None
    if "as-grown" in text or "as grown" in text or "as_grown" in text:
        state = "as_grown"
    elif "annealed" in text and "air" in text:
        state = "annealed_air"
    elif "annealed" in text and ("argon" in text or re.search(r"\bar\b", text)):
        state = "annealed_ar"
    elif "annealed" in text and ("nitrogen" in text or "n2" in text or "n 2" in text):
        state = "annealed_n2"
    else:
        return None
    return percent, state


def _evidence(item: dict) -> dict:
    entries = item.get("evidence")
    if isinstance(entries, dict):
        entries = [entries]
    elif isinstance(entries, str):
        entries = [{"text_snippet": entries, "locator": item.get("locator"), "page": item.get("page")}]
    elif not isinstance(entries, list):
        entries = []
    source = item.get("source")
    if isinstance(source, dict):
        entries.append(source)
    if item.get("locator") or item.get("page"):
        entries.append({"locator": item.get("locator"), "page": item.get("page"),
                        "text_snippet": item.get("evidence") if isinstance(item.get("evidence"), str) else None})
    return {
        "table_locator": any((e.get("source_type") == "table" or "row=" in str(e.get("locator", "")))
                             and bool(e.get("locator") or e.get("table_id")) for e in entries if isinstance(e, dict)),
        "page_locator": any(e.get("page") is not None or "page=" in str(e.get("locator", ""))
                            for e in entries if isinstance(e, dict)),
        "verbatim_snippet": any(bool(e.get("text_snippet") or e.get("snippet"))
                                for e in entries if isinstance(e, dict)),
    }


def _expected(case_id: str, gold: dict) -> tuple[list[dict], dict[str, tuple[str, ...]]]:
    points = []
    if case_id == "SEM-GOLD-A":
        for row in gold["rows"]:
            for prop, value in (
                ("carrier_concentration", row["carrier_concentration_scaled"] * 1e20),
                ("hall_mobility", row["hall_mobility"]),
                ("resistivity", row["resistivity_scaled"] * 1e-3),
                ("sheet_resistance", row["sheet_resistance"]),
                ("optical_band_gap", row["optical_band_gap"]),
            ):
                points.append({"sample": row["film"], "property": prop, "value": value})
        return points, _A_PROPERTIES
    for row in gold["rows"]:
        sample = [row["al_atomic_percent"], row["state"]]
        for prop in _B_PROPERTIES:
            value = row[prop]
            if value is not None:
                points.append({"sample": sample, "property": prop, "value": value})
    return points, _B_PROPERTIES


def score_raw_case(raw: dict, gold: dict) -> dict:
    case_id = gold["case_id"]
    expected, aliases = _expected(case_id, gold)
    materials = {str(item.get("local_id")): item for item in raw.get("materials", [])
                 if isinstance(item, dict)}
    records = _records(raw)
    indexed: dict[tuple, list[dict]] = {}
    for item in records:
        prop = _property(item)
        if prop not in {alias for names in aliases.values() for alias in names}:
            continue
        sample = _a_sample(item, materials) if case_id == "SEM-GOLD-A" else _b_sample(item, materials)
        if sample is None:
            continue
        key = (tuple(sample) if isinstance(sample, tuple) else sample, prop)
        indexed.setdefault(key, []).append(item)
    matches = []
    for point in expected:
        sample = tuple(point["sample"]) if isinstance(point["sample"], list) else point["sample"]
        candidates = [item for prop in aliases[point["property"]]
                      for item in indexed.get((sample, prop), [])]
        exact_candidates = [item for item in candidates if (
            (actual := _physical_value(item)) is not None
            and math.isclose(actual, point["value"], rel_tol=1e-7, abs_tol=1e-12)
            and _unit_key(item.get("unit")) in _EXPECTED_UNITS[point["property"]]
        )]
        chosen = exact_candidates[0] if len(exact_candidates) == 1 else None
        matches.append({
            "sample": point["sample"], "property": point["property"],
            "expected_value": point["value"],
            "candidate_count": len(candidates), "exact_candidate_count": len(exact_candidates),
            "exact_value_and_unit": chosen is not None,
            "exact_property_key": bool(chosen and _property(chosen) == point["property"]),
            "observed_property_key": _property(chosen) if chosen else None,
            "observed_value": _physical_value(chosen) if chosen else None,
            "observed_unit": chosen.get("unit") if chosen else None,
            "evidence": _evidence(chosen) if chosen else None,
            "direct_focal_ownership": bool(chosen and chosen.get("ownership") == "focal_work"),
            "conditions": chosen.get("conditions") if chosen else None,
        })
    exact = [point for point in matches if point["exact_value_and_unit"]]
    samples = {tuple(point["sample"]) if isinstance(point["sample"], list) else point["sample"]
               for point in exact}
    audit = {
        "case_id": case_id, "source": "original_raw_provider_payload_only",
        "raw_record_count": len(records), "expected_points": len(expected),
        "exact_value_and_unit_points": len(exact),
        "exact_property_key_points": sum(point["exact_property_key"] for point in exact),
        "exact_sample_count": len(samples),
        "expected_sample_count": len(gold["rows"]),
        "table_locator_points": sum(point["evidence"]["table_locator"] for point in exact),
        "page_locator_points": sum(point["evidence"]["page_locator"] for point in exact),
        "verbatim_snippet_points": sum(point["evidence"]["verbatim_snippet"] for point in exact),
        "direct_focal_ownership_points": sum(point["direct_focal_ownership"] for point in exact),
        "point_details": matches,
        "canonical_admission_not_implied": True,
    }
    if case_id == "SEM-GOLD-A":
        audit["hall_specificity_points"] = sum(
            point["exact_property_key"] for point in exact if point["property"] == "hall_mobility"
        )
        audit["dopant_identity_samples"] = sum(
            any(row["film"] in str(material.get(key, ""))
                for material in materials.values()
                for key in ("formula", "chemical_formula", "composition_formula", "name"))
            for row in gold["rows"] if row["ga_atomic_percent"] > 0
        )
        audit["missing_measurement_temperature_preserved"] = all(
            not (point["conditions"] or {}).get("measurement_temperature") for point in exact
        )
    else:
        audit["missing_dash_cells_not_zero_filled"] = not any(
            _b_sample(item, materials) == (row["al_atomic_percent"], row["state"])
            and _property(item) == prop
            for row in gold["rows"] for prop in ("carrier_concentration", "carrier_mobility")
            if row[prop] is None for item in records
        )
        audit["room_temperature_condition_points"] = sum(
            str((point["conditions"] or {}).get("measurement_temperature", "")).casefold()
            in {"room temperature", "room_temperature"} for point in exact
        )
    return audit


def score_run(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    case_id = report["case_id"]
    lock = source_lock(case_id)
    gold = json.loads((ROOT / lock["gold_file"]).read_text(encoding="utf-8"))
    run_root = report_path.parent
    attempts = [item["attempt_number"] for item in report["attempts"] if item.get("payload_returned")]
    if not attempts:
        raise ValueError("Cannot scientifically score a run without a raw provider payload")
    attempt_root = run_root / f"attempt-{attempts[0]}"
    raw_path = _io_path(attempt_root / "raw_response.txt")
    recorded_digest = json.loads(_io_path(attempt_root / "raw_response_sha256.json").read_text(encoding="utf-8"))["sha256"]
    actual_digest = sha256(raw_path.read_bytes()).hexdigest()
    if actual_digest != recorded_digest:
        raise ValueError("Immutable raw provider hash mismatch")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ValueError("Raw provider payload is not a scoreable JSON object")
    scientific = score_raw_case(raw, gold)
    scored = {
        "scoring_version": "semiconductor_raw_scoring_v2_independent_numeric_check",
        "case_id": case_id, "model_id": report["model_id"], "run_id": report["run_id"],
        "raw_response_sha256": actual_digest,
        "scientifically_scoreable": scientific["exact_value_and_unit_points"] > 0,
        "sem_live_gate_qualifying": scientific["exact_value_and_unit_points"] > 0,
        "raw_scientific_score": scientific,
        "schema_valid": report["schema_valid"],
        "canonical_admission": report["canonical_admission"],
        "deterministic_expected_points": gold["canonical_result_count"],
        "original_report": str(report_path),
    }
    destination = run_root / "scored_report_v2.json"
    with destination.open("xb") as stream:
        stream.write((json.dumps(scored, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({
        "case_id": case_id, "model_id": report["model_id"],
        "run_id": report["run_id"], "raw_hash_verified": True,
        "exact_value_and_unit_points": scientific["exact_value_and_unit_points"],
        "expected_points": scientific["expected_points"],
        "exact_property_key_points": scientific["exact_property_key_points"],
        "sem_live_gate_qualifying": scored["sem_live_gate_qualifying"],
        "artifact": str(destination),
    }, ensure_ascii=True))
    return scored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    score_run(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
