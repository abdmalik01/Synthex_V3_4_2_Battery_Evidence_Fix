"""Strict assertion scoring for the frozen MECH-CREEP-B Table 2 cells."""

from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.visual.analytics.projection import project_archives


_PROPERTIES = (
    ("rupture_time_h", "rupture_time", "h", "t_rup"),
    ("rupture_strain_percent", "rupture_strain", "%", "epsilon_rup"),
    ("time_to_1_percent_h", "time_to_specific_strain", "h", "t_1%"),
)


def score_creep_b(archive: SynthexArchive, gold: dict) -> dict:
    if gold["case_id"] != "MECH-CREEP-B" or gold["status"] != "locked_reviewed":
        raise ValueError("MECH-CREEP-B requires frozen reviewed gold")
    if archive.metadata.domain != "mechanical":
        raise ValueError("MECH-CREEP-B requires a Mechanical archive")
    rows = project_archives([archive])
    results = []
    for source_row in gold["rows"]:
        for key, property_name, unit, reported_term in _PROPERTIES:
            raw = source_row[key]
            value = float(raw)
            property_rows = [row for row in rows if (
                row.modality == "experimental" and row.property_name == property_name
                and row.record_type == "creep_stress_rupture"
            )]
            value_rows = [row for row in property_rows if (
                row.value == value and row.unit == unit and row.raw_value == raw
            )]
            association_rows = [row for row in value_rows if (
                row.material_label == gold["gold_basis"]["sample"]
                and row.conditions.get("processing_state") == gold["gold_basis"]["processing_state"]
                and row.conditions.get("test_temperature") == source_row["test_temperature_c"]
                and row.conditions.get("applied_stress") == source_row["applied_stress_mpa"]
                and row.conditions.get("test_environment") == gold["gold_basis"]["environment"]
            )]
            type_rows = [row for row in association_rows if (
                row.conditions.get("scientific_type") == "reported_measurement"
                and row.conditions.get("data_kind") == "scalar"
                and row.conditions.get("reported_term") == reported_term
            )]
            evidence_rows = [row for row in type_rows if any(
                ref.get("page") == gold["gold_basis"]["page"]
                and ref.get("table_id", "").startswith("tbl-")
                and ref.get("text_snippet") == raw
                and f"row={source_row['table_row']};" in ref.get("locator", "")
                and ref.get("verbatim_match") is True
                for ref in row.evidence_references
            )]
            results.append({
                "table_row": source_row["table_row"], "property": property_name,
                "value_correct": bool(value_rows), "association_correct": bool(association_rows),
                "scientific_type_correct": bool(type_rows), "source_tracked": bool(evidence_rows),
                "passed": bool(evidence_rows),
            })
    excluded = []
    for item in gold["excluded_source_rows"]:
        admitted = any(row.modality == "experimental" and (
            row.conditions.get("test_temperature") == item["test_temperature_c"]
            and row.conditions.get("applied_stress") == item["applied_stress_mpa"]
        ) for row in rows)
        excluded.append({**item, "excluded": not admitted})
    total = len(results)
    if total != gold["assertion_count"]:
        raise ValueError("Creep gold assertion count changed")
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in results),
        "total": total, "assertions": results,
        "value_accuracy": sum(item["value_correct"] for item in results) / total,
        "association_accuracy": sum(item["association_correct"] for item in results) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in results) / total,
        "source_tracking": sum(item["source_tracked"] for item in results) / total,
        "excluded_rows": excluded,
        "excluded_row_correctness": sum(item["excluded"] for item in excluded) / len(excluded),
        "admitted_rows": len(rows),
    }
