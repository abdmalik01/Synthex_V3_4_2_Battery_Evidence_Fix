"""Frozen-gold scorer for MECH-HARD-D."""

from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive


def score_hard_d(archive: SynthexArchive, gold: dict) -> dict:
    materials = {item.material_id: item for item in archive.materials}
    assertions = []
    for expected in gold["rows"]:
        candidates = []
        for experiment in archive.experiments:
            material = materials.get(experiment.material_ids[0]) if len(experiment.material_ids) == 1 else None
            for output in experiment.outputs:
                if output.property == "vickers_hardness" and output.raw_value == expected["raw_value"]:
                    candidates.append((experiment, material, output))
        value_rows = [item for item in candidates if (
            item[2].value == expected["value"] and item[2].unit == "HV"
            and item[2].uncertainty == expected["uncertainty"]
            and item[2].uncertainty_unit == "HV"
        )]
        association_rows = [item for item in value_rows if (
            item[1] is not None and item[1].name == expected["sample"]
            and item[2].conditions.get("cooling_rate") == float(expected["cooling_rate_c_per_s"])
            and item[2].conditions.get("hardness_scale") == "Vickers"
            and item[2].conditions.get("test_load_kgf") == 0.5
            and item[2].conditions.get("number_of_indents") == 5
            and item[2].conditions.get("dwell_time") == "not_reported"
        )]
        scientific_rows = [item for item in association_rows if (
            item[2].conditions.get("scientific_type") == "reported_measurement"
            and item[2].conditions.get("reported_term") == "Micro-Vickers hardness"
        )]
        evidence_rows = [item for item in scientific_rows if any(
            evidence.page == 12 and evidence.table_id and evidence.verbatim_match is True
            and evidence.text_snippet == expected["raw_value"]
            and f"row={expected['table_row']};" in (evidence.locator or "")
            for evidence in item[2].evidence
        )]
        assertions.append({
            "table_row": expected["table_row"], "sample": expected["sample"],
            "value_correct": bool(value_rows), "association_correct": bool(association_rows),
            "scientific_type_correct": bool(scientific_rows), "source_tracked": bool(evidence_rows),
            "passed": bool(evidence_rows),
        })
    total = len(assertions)
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": total, "assertions": assertions,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "association_accuracy": sum(item["association_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "scale_safety": all(
            output.property == "vickers_hardness" and output.unit == "HV"
            for experiment in archive.experiments for output in experiment.outputs
        ),
        "admitted_rows": sum(len(item.outputs) for item in archive.experiments),
    }
