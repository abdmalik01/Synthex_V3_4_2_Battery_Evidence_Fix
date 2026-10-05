"""Frozen-gold scorer for MECH-COMPUTE-F."""

from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive


def score_compute_f(archive: SynthexArchive, gold: dict) -> dict:
    materials = {item.material_id: item for item in archive.materials}
    assertions = []
    for expected in gold["rows"]:
        candidates = []
        for calculation in archive.calculations:
            material = materials.get(calculation.material_ids[0]) if len(calculation.material_ids) == 1 else None
            for output in calculation.outputs:
                if output.property == expected["property"] and material and material.name == expected["material"]:
                    candidates.append((calculation, material, output))
        values = [item for item in candidates if (
            item[2].raw_value == expected["raw_value"] and item[2].value == expected["value"]
            and item[2].unit == expected["unit"]
        )]
        scientific = [item for item in values if (
            item[2].conditions.get("scientific_type") == "simulation_result"
            and item[2].conditions.get("reported_term") == expected["reported_term"]
        )]
        method = [item for item in scientific if (
            item[0].code == "CASTEP" and item[0].method == "density functional theory"
            and item[0].functional == "CA-PZ local density approximation (LDA)"
            and item[0].model.get("k_point_grid") == "2x2x2"
            and item[0].model.get("cutoff_energy_ev") == 360
        )]
        evidence = [item for item in method if any(
            ev.page == expected["page"] and ev.table_id and ev.verbatim_match is True
            and ev.text_snippet == expected["raw_value"]
            and f"row={expected['table_row']};" in (ev.locator or "") and "bbox=" in (ev.locator or "")
            for ev in item[2].evidence
        )]
        assertions.append({
            "table": expected["table"], "material": expected["material"],
            "property": expected["property"], "value_correct": bool(values),
            "scientific_type_correct": bool(scientific), "method_correct": bool(method),
            "source_tracked": bool(evidence), "passed": bool(evidence),
        })
    total = len(assertions)
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": total, "assertions": assertions,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "method_accuracy": sum(item["method_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "experiment_separation": len(archive.experiments) == 0,
        "calculations": len(archive.calculations),
        "calculation_outputs": sum(len(item.outputs) for item in archive.calculations),
    }
