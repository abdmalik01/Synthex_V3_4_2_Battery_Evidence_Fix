"""Audit the preserved, schema-invalid AM-DENS-B provider payload.

This scorer deliberately does not treat the payload as a canonical archive.  It only
quantifies scientific content that can be matched directly to the frozen gold rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


COORDINATES = {
    "laser_power": "laser_power_w",
    "scan_speed": "scan_speed_mm_s",
    "hatch_spacing": "hatch_spacing_mm",
    "rotation_angle": "rotation_angle_deg",
    "volumetric_energy_density": "volumetric_energy_density_j_mm3",
}


def _number(field: dict) -> float:
    return float(field["raw_value"])


def audit_raw_payload(payload: dict, gold: dict) -> dict:
    steps = {step.get("output_material_id"): step for step in payload.get("processing_steps", [])}
    archimedes = {
        measurement.get("material_id"): measurement
        for measurement in payload.get("measurements", [])
        if measurement.get("property") == "relative_density"
        and measurement.get("method") == "Archimedes method"
    }
    assertions = []
    for expected in gold["rows"]:
        material_id = f'material_sample_{expected["sample"]}'
        step = steps.get(material_id)
        measurement = archimedes.get(material_id)
        coordinate_checks = {
            raw_name: bool(
                step
                and raw_name in step
                and _number(step[raw_name]) == float(expected[gold_name])
            )
            for raw_name, gold_name in COORDINATES.items()
        }
        value_match = bool(
            measurement
            and _number(measurement["value"]) == float(expected["relative_density_pct"])
            and measurement["value"].get("unit") == "%"
        )
        lineage_match = bool(
            step
            and step.get("input_material_id") == "material_feedstock_powder"
            and step.get("output_material_id") == material_id
            and measurement
            and measurement.get("material_id") == material_id
        )
        assertions.append(
            {
                "sample": expected["sample"],
                "coordinates": coordinate_checks,
                "coordinate_match": all(coordinate_checks.values()),
                "relative_density_match": value_match,
                "lineage_match": lineage_match,
                "ownership_label": bool(
                    step
                    and measurement
                    and step.get("ownership") == "focal_work"
                    and measurement.get("ownership") == "focal_work"
                ),
                "canonical_evidence": False,
            }
        )

    measurements = payload.get("measurements", [])
    properties = {m.get("property") for m in measurements}
    forbidden_process_keys = {"linear_energy_density", "surface_energy_density"}
    extra_measurements = [
        {
            "material_id": item.get("material_id"),
            "method": item.get("method"),
            "value": item.get("value", {}).get("raw_value"),
            "source_table": "Table 6",
        }
        for item in measurements
        if item.get("method") != "Archimedes method"
    ]
    total = len(assertions)
    return {
        "case_id": gold["case_id"],
        "assessment_scope": "scientific content in preserved raw payload; not a canonical archive score",
        "schema_admissible": False,
        "canonical_raw_score": None,
        "coordinate_association": {
            "passed": sum(item["coordinate_match"] for item in assertions),
            "total": total,
            "accuracy": sum(item["coordinate_match"] for item in assertions) / total,
        },
        "relative_density_association": {
            "passed": sum(item["relative_density_match"] for item in assertions),
            "total": total,
            "accuracy": sum(item["relative_density_match"] for item in assertions) / total,
        },
        "lineage_association": {
            "passed": sum(item["lineage_match"] for item in assertions),
            "total": total,
            "accuracy": sum(item["lineage_match"] for item in assertions) / total,
        },
        "ownership_labels": {
            "passed": sum(item["ownership_label"] for item in assertions),
            "total": total,
            "accuracy": sum(item["ownership_label"] for item in assertions) / total,
            "admissible": False,
            "reason": "the enclosing payload failed the canonical schema",
        },
        "canonical_evidence": {
            "passed": 0,
            "total": total,
            "accuracy": 0.0,
            "reason": "free-text table references are not canonical page/cell evidence objects",
        },
        "scientific_safety": {
            "relative_density_not_converted_to_porosity": "porosity" not in properties,
            "relative_density_not_converted_to_absolute_density": "absolute_density" not in properties,
            "no_unreported_energy_density_family": all(
                key not in step
                for step in payload.get("processing_steps", [])
                for key in forbidden_process_keys
            ),
            "missing_build_orientation_not_inferred": all(
                "build_orientation" not in step for step in payload.get("processing_steps", [])
            ),
            "specimen_rows_not_collapsed": len(steps) == total,
        },
        "extra_source_supported_measurements": extra_measurements,
        "assertions": assertions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_raw_payload(
        json.loads(args.payload.read_text(encoding="utf-8")),
        json.loads(args.gold.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
