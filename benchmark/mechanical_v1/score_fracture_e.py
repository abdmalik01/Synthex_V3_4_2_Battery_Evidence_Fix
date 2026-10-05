"""Frozen-gold scorer for MECH-FRACTURE-E."""

from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive


def score_fracture_e(archive: SynthexArchive, gold: dict) -> dict:
    materials = {item.material_id: item for item in archive.materials}
    assertions = []
    for expected in gold["rows"]:
        candidates = []
        for experiment in archive.experiments:
            material = materials.get(experiment.material_ids[0]) if len(experiment.material_ids) == 1 else None
            for output in experiment.outputs:
                if output.property == "fracture_toughness" and output.conditions.get("sample") == expected["sample"]:
                    candidates.append((material, output))
        value_rows = [item for item in candidates if (
            item[1].raw_value == expected["raw_value"] and item[1].value == expected["value"]
            and item[1].unit == "MPa*sqrt(m)"
        )]
        association_rows = [item for item in value_rows if (
            item[0] is not None and expected["treatment"] in item[0].tags
            and item[1].conditions.get("processing_state") == expected["treatment"]
            and item[1].conditions.get("test_temperature_c") == expected["test_temperature_c"]
            and item[1].conditions.get("specimen_type") == "pre-cracked Charpy V-notch"
        )]
        metric_rows = [item for item in association_rows if (
            item[1].conditions.get("reported_metric") == expected["reported_metric"]
            and item[1].conditions.get("reported_term") == expected["reported_metric"]
            and item[1].conditions.get("validity") == expected["validity"]
            and item[1].conditions.get("scientific_type") == (
                "reported_measurement" if expected["reported_metric"] == "K_IC"
                else "reported_derived_metric"
            )
        )]
        evidence_rows = [item for item in metric_rows if any(
            evidence.page == 13 and evidence.table_id and evidence.verbatim_match is True
            and evidence.text_snippet == expected["raw_value"]
            and f"row={expected['table_row']};sample={expected['sample']};" in (evidence.locator or "")
            for evidence in item[1].evidence
        )]
        assertions.append({
            "sample": expected["sample"], "value_correct": bool(value_rows),
            "association_correct": bool(association_rows), "metric_validity_correct": bool(metric_rows),
            "source_tracked": bool(evidence_rows), "passed": bool(evidence_rows),
        })
    total = len(assertions)
    all_outputs = [output for experiment in archive.experiments for output in experiment.outputs]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": total, "assertions": assertions,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "association_accuracy": sum(item["association_correct"] for item in assertions) / total,
        "metric_validity_accuracy": sum(item["metric_validity_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "metric_safety": all(
            output.property == "fracture_toughness" and output.unit == "MPa*sqrt(m)"
            and output.conditions.get("reported_metric") in {"K_IC", "K_JC", "K_JU"}
            for output in all_outputs
        ),
        "conditional_count": sum(output.conditions.get("reported_metric") == "K_JC" for output in all_outputs),
        "invalid_count": sum(output.conditions.get("reported_metric") == "K_JU" for output in all_outputs),
        "admitted_rows": len(all_outputs),
    }
