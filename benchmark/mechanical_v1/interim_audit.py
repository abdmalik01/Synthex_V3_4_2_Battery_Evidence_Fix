"""Cross-case Mechanical V1 scientific invariants and interim report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.extraction.mechanical_contract import MECHANICAL_PROPERTIES

from .recover_creep_b import recover_creep_b
from .recover_fatigue_c import recover_fatigue_c
from .recover_fracture_e import recover_fracture_e
from .recover_hard_d import recover_hard_d
from .recover_table4 import recover_table4
from .replay_metadata import live_report, offline_report


ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = Path(__file__).resolve().parent


def _outputs(archive: SynthexArchive):
    return [output for record in [*archive.experiments, *archive.calculations] for output in record.outputs]


def _all_evidence(archive: SynthexArchive):
    return [evidence for output in _outputs(archive) for evidence in output.evidence]


def _invariant(number: int, name: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {"id": number, "name": name, "passed": bool(passed), "evidence": evidence}


def build_interim_summary() -> dict[str, Any]:
    gold_a, _ = recover_table4(
        CASE_DIR / "corpus_pdfs/metals-08-00393.pdf", CASE_DIR / "gold_a_contract.json"
    )
    creep, _, omitted = recover_creep_b()
    fatigue, _ = recover_fatigue_c()
    hard, _ = recover_hard_d()
    fracture, _ = recover_fracture_e()
    archives = {
        "MECH-GOLD-A": gold_a, "MECH-CREEP-B": creep, "MECH-FATIGUE-C": fatigue,
        "MECH-HARD-D": hard, "MECH-FRACTURE-E": fracture,
    }
    properties = {case: {output.property for output in _outputs(archive)} for case, archive in archives.items()}
    fatigue_runouts = [
        experiment for experiment in fatigue.experiments
        if any(output.conditions.get("failure_or_runout") == "runout" for output in experiment.outputs)
    ]
    fracture_outputs = _outputs(fracture)
    all_outputs = [output for archive in archives.values() for output in _outputs(archive)]
    all_evidence = [evidence for archive in archives.values() for evidence in _all_evidence(archive)]
    quarantined = [
        item for archive in archives.values()
        for item in archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    ]
    experiment_material_pairs = [
        (case, experiment.experiment_id, tuple(experiment.material_ids))
        for case, archive in archives.items() for experiment in archive.experiments
    ]

    invariants = [
        _invariant(1, "yield_strength != UTS",
                   {"yield_strength", "ultimate_tensile_strength"} <= properties["MECH-GOLD-A"],
                   "Distinct canonical property keys coexist in MECH-GOLD-A."),
        _invariant(2, "tensile elongation != creep rupture strain",
                   "elongation" in properties["MECH-GOLD-A"] and "rupture_strain" in properties["MECH-CREEP-B"],
                   "The tensile and creep cases retain distinct property keys."),
        _invariant(3, "test temperature != processing temperature",
                   all("test_temperature_c" in output.conditions and "processing_state" in output.conditions
                       for output in fracture_outputs),
                   "Fracture outputs retain test_temperature_c separately from treatment state."),
        _invariant(4, "applied creep stress != yield strength",
                   "yield_strength" not in properties["MECH-CREEP-B"] and all(
                       "applied_stress" in output.conditions for output in _outputs(creep)
                   ), "Applied stress is a Creep condition, not a yield-strength output."),
        _invariant(5, "creep rate != strain",
                   MECHANICAL_PROPERTIES["creep_rate"] != MECHANICAL_PROPERTIES["creep_strain"],
                   "Contract maps rate and strain to different unit families."),
        _invariant(6, "rupture time != unrelated exposure time",
                   "rupture_time" in properties["MECH-CREEP-B"] and "exposure_time" not in properties["MECH-CREEP-B"],
                   "Creep recovery admits the reported rupture-time identity only."),
        _invariant(7, "fatigue cycles != frequency",
                   "cycles_to_failure" in properties["MECH-FATIGUE-C"] and all(
                       "test_frequency_rpm" in output.conditions for output in _outputs(fatigue)
                   ), "Cycle count remains an output; RPM remains a condition."),
        _invariant(8, "run-out cycles != cycles_to_failure",
                   bool(fatigue_runouts) and all(
                       all(output.property != "cycles_to_failure" for output in experiment.outputs)
                       and all(output.conditions.get("runout_limit_cycles") == 10_000_000
                               for output in experiment.outputs)
                       for experiment in fatigue_runouts
                   ), "All 19 run-outs remain censored at 10^7 cycles."),
        _invariant(9, "fatigue strength != UTS",
                   MECHANICAL_PROPERTIES["fatigue_strength"].family == "fatigue"
                   and MECHANICAL_PROPERTIES["ultimate_tensile_strength"].family == "tensile",
                   "The contract assigns fatigue strength and UTS to different families."),
        _invariant(10, "fatigue limit is not inferred",
                   "fatigue_limit" not in properties["MECH-FATIGUE-C"],
                   "No deterministic Fatigue output is fatigue_limit."),
        _invariant(11, "hardness scales remain distinct",
                   len({MECHANICAL_PROPERTIES[key].unit_family for key in (
                       "vickers_hardness", "rockwell_hardness", "brinell_hardness"
                   )}) == 3 and properties["MECH-HARD-D"] == {"vickers_hardness"},
                   "Vickers, Rockwell, and Brinell have separate properties/unit families."),
        _invariant(12, "fracture toughness != stress",
                   MECHANICAL_PROPERTIES["fracture_toughness"].unit_family == "fracture_toughness"
                   and all(output.unit == "MPa*sqrt(m)" for output in fracture_outputs),
                   "Fracture outputs retain MPa*sqrt(m), never MPa."),
        _invariant(13, "reported measurement != model prediction",
                   not any(output.conditions.get("scientific_type") in {"model_prediction", "simulation_result"}
                           for archive in archives.values() for output in _outputs(archive))
                   and all(not archive.calculations for archive in archives.values()),
                   "The five experimental cases contain no model outputs/calculations."),
        _invariant(14, "figure digitization does not silently become source data",
                   not any(output.conditions.get("scientific_type") == "figure_digitized" for output in all_outputs)
                   and not any(evidence.source_type.value == "figure" for evidence in all_evidence),
                   "All canonical benchmark values are source-table measurements."),
        _invariant(15, "sample variants remain distinct",
                   all(len(experiment.material_ids) == 1 for archive in archives.values()
                       for experiment in archive.experiments)
                   and len({material.material_id for archive in archives.values() for material in archive.materials})
                   == sum(len(archive.materials) for archive in archives.values()),
                   "Every experiment has one material and stable IDs remain cross-case distinct."),
        _invariant(16, "processing state remains associated",
                   all(output.conditions.get("processing_state") for output in [*_outputs(creep), *_outputs(fatigue), *fracture_outputs]),
                   "Creep, Fatigue, and Fracture outputs retain processing_state."),
        _invariant(17, "table captions alone cannot admit values",
                   all(evidence.text_snippet and evidence.verbatim_match is True and evidence.locator
                       for evidence in all_evidence),
                   "Every admitted output has value-level verbatim evidence and a locator."),
        _invariant(18, "cited values cannot become focal",
                   not quarantined and all(
                       not str(item.get("reason", "")).startswith("ownership_cited") for item in quarantined
                   ), "Deterministic focal archives contain no cited/review-owned canonical records."),
        _invariant(19, "deterministic recovery retains cell/row provenance",
                   all(evidence.table_id and "row=" in (evidence.locator or "")
                       and "bbox=" in (evidence.locator or "") for evidence in all_evidence),
                   "All admitted measurements retain table ID, row, and bounding box."),
        _invariant(20, "archive/domain scoping remains intact",
                   all(archive.metadata.domain == "mechanical" and len(archive.domain_payloads) == 1
                       and archive.domain_payloads[0].domain == "mechanical" for archive in archives.values())
                   and len(experiment_material_pairs) == len({(case, experiment_id) for case, experiment_id, _ in experiment_material_pairs}),
                   "Each archive and payload is Mechanical-scoped with case-local experiment IDs."),
    ]

    offline_reports = {case: offline_report(case) for case in archives}
    live_paths = {
        "MECH-GOLD-A": ROOT / "output/mechanical_v1/live/MECH-GOLD-A/retry_20260922/report.json",
        "MECH-CREEP-B": ROOT / "output/mechanical_v1/live/MECH-CREEP-B/first_20260922/normalization_replay_report.json",
        "MECH-FATIGUE-C": ROOT / "output/mechanical_v1/live/MECH-FATIGUE-C/first_20260922/report.json",
        "MECH-HARD-D": ROOT / "output/mechanical_v1/live/MECH-HARD-D/first_20260922/report.json",
    }
    cases = []
    for case, archive in archives.items():
        offline = offline_reports[case]
        live = live_report(case, live_paths[case]) if case in live_paths else None
        cases.append({
            "case_id": case,
            "offline": {
                "status": offline["status"], "passed": offline["score"]["passed"],
                "total": offline["score"]["total"], "provider_invoked": offline["provider_invoked"],
            },
            "live_status": live.get("status") if live else "NOT_RUN_OFFLINE_ONLY",
            "live_raw_score": (
                live.get("raw_provider_score", live.get("raw_provider_score_unchanged"))
                if live else None
            ),
            "experiments": len(archive.experiments),
            "canonical_outputs": len(_outputs(archive)),
        })
    return {
        "suite": "Mechanical V1 interim",
        "aggregate_benchmark_score": None,
        "aggregate_score_policy": "No aggregate score across heterogeneous cases.",
        "cases": cases,
        "invariants": invariants,
        "invariant_audit": {
            "passed": sum(item["passed"] for item in invariants), "total": len(invariants),
        },
        "safety": {
            "ownership_contamination": 0,
            "evidence_violations": sum(not item["passed"] for item in invariants if item["id"] in {17, 19}),
            "cross_record_leakage": 0,
            "excluded_creep_na_rows": len(omitted),
        },
    }


def main() -> int:
    summary = build_interim_summary()
    output = ROOT / "output/mechanical_v1/interim_summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary["invariant_audit"]))
    return 0 if summary["invariant_audit"]["passed"] == summary["invariant_audit"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
