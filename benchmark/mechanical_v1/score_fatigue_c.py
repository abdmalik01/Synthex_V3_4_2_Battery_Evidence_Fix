"""Source-grounded score for selected A1/A2 fatigue points and run-outs."""

from __future__ import annotations

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.visual.analytics.projection import project_archives


def score_fatigue_c(archive: SynthexArchive, gold: dict) -> dict:
    if gold["case_id"] != "MECH-FATIGUE-C" or gold["status"] != "locked_reviewed":
        raise ValueError("MECH-FATIGUE-C requires frozen reviewed gold")
    if archive.metadata.domain != "mechanical":
        raise ValueError("MECH-FATIGUE-C requires a Mechanical archive")
    rows = project_archives([archive])
    assertions = []
    runout_checks = []
    for source_row in gold["rows"]:
        page = 13 if source_row["table"] == "A1" else 14
        expected = [(
            "stress_amplitude", source_row["stress_amplitude_mpa"],
            float(source_row["stress_amplitude_mpa"]), "MPa", "Stress Amplitude",
        )]
        if source_row["outcome"] == "failure":
            expected.append((
                "cycles_to_failure", source_row["cycles_to_failure"],
                float(source_row["cycles_to_failure"].replace(",", "")),
                "cycles", "Cycles to Failure",
            ))
        for property_name, raw, value, unit, reported_term in expected:
            property_rows = [row for row in rows if (
                row.modality == "experimental" and row.record_type == "rotating_bending_fatigue"
                and row.property_name == property_name
            )]
            value_rows = [row for row in property_rows if (
                row.raw_value == raw and row.value == value and row.unit == unit
            )]
            association_rows = [row for row in value_rows if (
                row.material_label == gold["gold_basis"]["sample"]
                and row.conditions.get("processing_state") == gold["gold_basis"]["processing_state"]
                and row.conditions.get("orientation") == source_row["orientation"]
                and row.conditions.get("loading_mode") == gold["gold_basis"]["loading_mode"]
                and row.conditions.get("stress_ratio") == gold["gold_basis"]["stress_ratio"]
                and row.conditions.get("test_frequency_rpm") == source_row["test_frequency_rpm"]
                and row.conditions.get("test_frequency_raw") == f"{source_row['test_frequency_rpm']} RPM"
                and row.conditions.get("failure_or_runout") == source_row["outcome"]
            )]
            expected_kind = "series_point" if source_row["outcome"] == "failure" else "scalar"
            type_rows = [row for row in association_rows if (
                row.conditions.get("scientific_type") == "reported_measurement"
                and row.conditions.get("reported_term") == reported_term
                and row.conditions.get("data_kind") == expected_kind
                and row.conditions.get("curve_role") == (
                    "curve_point" if source_row["outcome"] == "failure" else "scalar"
                )
                and (source_row["outcome"] != "failure" or (
                    row.conditions.get("series_origin") == "source_table"
                    and row.conditions.get("series_id") == f"Table {source_row['table']}"
                ))
            )]
            evidence_rows = [row for row in type_rows if any(
                ref.get("page") == page
                and ref.get("table_id", "").startswith("tbl-")
                and ref.get("text_snippet") == raw
                and f"row={source_row['table_row']};" in ref.get("locator", "")
                and ref.get("verbatim_match") is True
                for ref in row.evidence_references
            )]
            assertions.append({
                "table": source_row["table"], "table_row": source_row["table_row"],
                "property": property_name, "value_correct": bool(value_rows),
                "association_correct": bool(association_rows),
                "scientific_type_correct": bool(type_rows),
                "source_tracked": bool(evidence_rows), "passed": bool(evidence_rows),
            })
        if source_row["outcome"] == "runout":
            amplitude_rows = [row for row in rows if (
                row.property_name == "stress_amplitude"
                and row.raw_value == source_row["stress_amplitude_mpa"]
                and row.conditions.get("orientation") == source_row["orientation"]
                and row.conditions.get("failure_or_runout") == "runout"
                and any(f"row={source_row['table_row']};" in ref.get("locator", "")
                        and ref.get("page") == page for ref in row.evidence_references)
            )]
            safe = bool(amplitude_rows) and all(
                not any(other.experiment_id == row.experiment_id and other.property_name == "cycles_to_failure"
                        for other in rows)
                and row.conditions.get("runout_limit_cycles") == 10000000
                for row in amplitude_rows
            )
            runout_checks.append({
                "table": source_row["table"], "table_row": source_row["table_row"],
                "censoring_correct": safe,
            })
    total = len(assertions)
    if total != gold["assertion_count"]:
        raise ValueError("Fatigue gold assertion count changed")
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": total, "assertions": assertions,
        "value_accuracy": sum(item["value_correct"] for item in assertions) / total,
        "association_accuracy": sum(item["association_correct"] for item in assertions) / total,
        "scientific_type_accuracy": sum(item["scientific_type_correct"] for item in assertions) / total,
        "source_tracking": sum(item["source_tracked"] for item in assertions) / total,
        "runout_checks": runout_checks,
        "runout_correctness": sum(item["censoring_correct"] for item in runout_checks) / len(runout_checks),
        "admitted_rows": len(rows),
    }
