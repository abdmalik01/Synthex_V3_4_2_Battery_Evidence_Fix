"""Scientific-content audit for a preserved, schema-invalid AM-GOLD-A payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def _number(field: dict) -> float:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(field["raw_value"]))
    if not match:
        raise ValueError(f"No numeric value in {field!r}")
    return float(match.group())


def audit_raw_gold_a(payload: dict, gold: dict) -> dict:
    expected = {row["sample"]: row for row in gold["rows"]}
    processes = {item.get("local_id"): item for item in payload.get("processes", [])}
    materials = {item.get("local_id"): item for item in payload.get("materials", [])}
    relative_density = [m for m in payload.get("measurements", []) if m.get("property") == "relative_density"]
    assertions = []
    for measurement in relative_density:
        process = processes.get(measurement.get("process_id"), {})
        sample = str(process.get("local_id", "")).removeprefix("process_")
        row = expected.get(sample)
        material_id = measurement.get("material_id")
        coordinate_match = bool(row and all((
            _number(process["laser_power"]) == row["laser_power_w"],
            _number(process["scan_speed"]) == row["scan_speed_mm_s"],
            _number(process["hatch_spacing"]) == row["hatch_spacing_mm"],
        )))
        value_match = bool(row and _number(measurement["value"]) == row["relative_density_pct"])
        lineage_match = bool(process.get("target_material_id") == material_id and material_id in materials)
        source = measurement.get("source", {})
        assertions.append({
            "sample": sample, "coordinate_match": coordinate_match,
            "relative_density_match": value_match, "lineage_match": lineage_match,
            "canonical_evidence": bool(source.get("page") and source.get("locator")),
            "ownership_label": measurement.get("ownership") == "focal_work",
        })
    base = processes.get("process_base_setup", {})
    feedstock = materials.get("material_1", {})
    measurements = payload.get("measurements", [])
    powder_values = {
        item.get("property"): _number(item["value"])
        for item in measurements
        if item.get("material_id") == "material_1" and item.get("property", "").endswith("particle size")
    }
    recovered = len(assertions)
    total = len(expected)
    return {
        "case_id": gold["case_id"],
        "assessment_scope": "scientific content in preserved raw payload; canonical envelope remained invalid",
        "schema_admissible": False,
        "canonical_raw_score": None,
        "row_recovery": {"passed": recovered, "total": total, "accuracy": recovered / total},
        "coordinate_association": {"passed": sum(a["coordinate_match"] for a in assertions), "recovered": recovered, "gold_total": total},
        "relative_density_association": {"passed": sum(a["relative_density_match"] for a in assertions), "recovered": recovered, "gold_total": total},
        "lineage_association": {"passed": sum(a["lineage_match"] for a in assertions), "recovered": recovered, "gold_total": total},
        "canonical_evidence": {"passed": sum(a["canonical_evidence"] for a in assertions), "recovered": recovered},
        "measurement_ownership": {"passed": sum(a["ownership_label"] for a in assertions), "recovered": recovered},
        "feedstock": {
            "identity_correct": "tungsten" in feedstock.get("name", "").casefold(),
            "spherical_morphology_retained_in_evidence": "spherical" in feedstock.get("evidence", "").casefold(),
            "particle_sizes_correct": powder_values == {"D10 particle size": 10.0, "D50 particle size": 15.87, "D90 particle size": 24.86},
        },
        "build_context": {
            "machine": base.get("machine_model") == "SLM 280HL",
            "preheat": _number(base.get("preheat_temperature", {})) == 423.15,
            "atmosphere": base.get("shielding_gas") == "argon",
            "oxygen_limit": _number(base.get("chamber_oxygen", {})) == 300,
            "scan_strategy": base.get("scan_strategy") == "zigzag",
            "rotation_angle": _number(base.get("rotation_angle", {})) == 67,
            "layer_thickness": _number(base.get("layer_thickness", {})) == 0.03,
        },
        "scientific_safety": {
            "no_invented_energy_density": not any("energy_density" in key for item in payload.get("processes", []) for key in item),
            "relative_density_not_converted_to_porosity": not any(item.get("property") == "porosity" for item in measurements),
            "missing_orientation_not_inferred": not any("orientation" in key for item in payload.get("processes", []) for key in item),
            "omitted_gold_rows": sorted(set(expected) - {a["sample"] for a in assertions}),
        },
        "assertions": assertions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_raw_gold_a(json.loads(args.payload.read_text(encoding="utf-8")), json.loads(args.gold.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
