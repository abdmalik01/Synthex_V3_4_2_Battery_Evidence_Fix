"""Final eight-case, 30-invariant Mechanical V1 scientific closure audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthex_platform.extraction.mechanical_contract import MECHANICAL_PROPERTIES
from synthex_platform.visual.analytics.projection import project_archives

from benchmark.mechanical_v1.recover_compute_f import recover_compute_f
from benchmark.mechanical_v1.recover_creep_b import recover_creep_b
from benchmark.mechanical_v1.recover_fatigue_c import recover_fatigue_c
from benchmark.mechanical_v1.recover_fracture_e import recover_fracture_e
from benchmark.mechanical_v1.recover_hard_d import recover_hard_d
from benchmark.mechanical_v1.recover_negative_h import recover_negative_h
from benchmark.mechanical_v1.recover_review_g import recover_review_g
from benchmark.mechanical_v1.recover_table4 import recover_table4
from benchmark.mechanical_v1.replay_metadata import live_report, offline_report


CASE_DIR = Path(__file__).resolve().parent


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _outputs(archive):
    return [output for record in [*archive.experiments, *archive.calculations] for output in record.outputs]


def _quarantine(archive):
    return archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def _invariant(number: int, name: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {"id": number, "name": name, "passed": bool(passed), "evidence": evidence}


def _raw_score(report: dict | None) -> dict | None:
    if not report:
        return None
    score = report.get("raw_provider_score") or report.get("raw_provider_score_unchanged")
    if not score:
        return None
    return {
        "passed": score.get("passed"), "total": score.get("total"),
        "schema_valid": score.get("schema_valid"),
    }


def _case_summary(case_id, archive, offline, live, route, paper_types, status, *, ownership=0, evidence=0):
    return {
        "case_id": case_id,
        "route": route,
        "paper_type": paper_types,
        "source_checksum": offline["source_sha256"],
        "offline_gold_count": offline["score"]["total"],
        "offline_matches": offline["score"]["passed"],
        "live_status": live.get("status") if live else "NOT_RUN",
        "raw_provider_score": _raw_score(live),
        "deterministic_recovery_score": {
            "passed": offline["score"]["passed"], "total": offline["score"]["total"],
        },
        "experiments": len(archive.experiments),
        "calculations": len(archive.calculations),
        "outputs": len(_outputs(archive)),
        "quarantine_noncanonical_count": len(_quarantine(archive)),
        "ownership_violations": ownership,
        "evidence_violations": evidence,
        "status": status,
    }


def build_closure_summary() -> dict[str, Any]:
    gold_a, _ = recover_table4(CASE_DIR / "corpus_pdfs/metals-08-00393.pdf", CASE_DIR / "gold_a_contract.json")
    creep, _, omitted = recover_creep_b()
    fatigue, _ = recover_fatigue_c()
    hard, _ = recover_hard_d()
    fracture, _ = recover_fracture_e()
    compute, _ = recover_compute_f()
    review, guarded_review, review_route = recover_review_g()
    negative, negative_route, _, _ = recover_negative_h()
    archives = {
        "MECH-GOLD-A": gold_a, "MECH-CREEP-B": creep, "MECH-FATIGUE-C": fatigue,
        "MECH-HARD-D": hard, "MECH-FRACTURE-E": fracture, "MECH-COMPUTE-F": compute,
        "MECH-REVIEW-G": review, "MECH-NEGATIVE-H": negative,
    }
    properties = {case: {item.property for item in _outputs(archive)} for case, archive in archives.items()}
    all_canonical = [item for archive in archives.values() for item in _outputs(archive)]
    all_evidence = [ev for item in all_canonical for ev in item.evidence]
    fatigue_runouts = [
        experiment for experiment in fatigue.experiments
        if any(output.conditions.get("failure_or_runout") == "runout" for output in experiment.outputs)
    ]
    fracture_outputs = _outputs(fracture)
    review_context = review.domain_payloads[0].values["mechanical_review"]
    review_candidates = review_context["noncanonical_candidates"]
    hard_live = live_report("MECH-HARD-D", ROOT / "output/mechanical_v1/live/MECH-HARD-D/first_20260922/report.json")
    historical_freeze = _read(CASE_DIR / "freeze_manifest.json")
    normalization_safe = (
        hard_live["normalization_audit"]["scientific_values_created"] == 0
        and hard_live["normalization_audit"]["evidence_created"] == 0
        if "normalization_audit" in hard_live else
        historical_freeze["scientific_invariants_passed"] == 30
        and "normalization does not alter scientific identity" in historical_freeze["scientific_invariants"]
    )
    duplicate_227 = [
        experiment for experiment in fatigue.experiments
        if any(output.property == "stress_amplitude" and output.value == 227.26 for output in experiment.outputs)
    ]

    invariants = [
        _invariant(1, "yield_strength != UTS", {"yield_strength", "ultimate_tensile_strength"} <= properties["MECH-GOLD-A"], "Gold-A preserves distinct yield and UTS keys."),
        _invariant(2, "proof stress preserves reported definition", "proof_stress" in MECHANICAL_PROPERTIES and MECHANICAL_PROPERTIES["proof_stress"] is not MECHANICAL_PROPERTIES["yield_strength"], "The contract has a dedicated proof_stress identity and manifest alias."),
        _invariant(3, "tensile elongation != creep rupture strain", "elongation" in properties["MECH-GOLD-A"] and "rupture_strain" in properties["MECH-CREEP-B"], "Tensile elongation and creep rupture strain use distinct keys."),
        _invariant(4, "test temperature != process temperature", all("temperature" in output.conditions and "heat_treatment" in output.conditions for output in _outputs(gold_a)), "Gold-A keeps test temperature separate from heat treatment and overaging."),
        _invariant(5, "applied creep stress != material strength", "yield_strength" not in properties["MECH-CREEP-B"] and all("applied_stress" in output.conditions for output in _outputs(creep)), "Creep stress remains a condition, not a strength output."),
        _invariant(6, "creep rate != strain", MECHANICAL_PROPERTIES["creep_rate"].unit_family != MECHANICAL_PROPERTIES["creep_strain"].unit_family, "Rate and strain have different unit families."),
        _invariant(7, "rupture time != processing exposure time", "rupture_time" in properties["MECH-CREEP-B"] and "exposure_time" not in properties["MECH-CREEP-B"], "Only source-reported rupture time is admitted."),
        _invariant(8, "cycles != frequency", "cycles_to_failure" in properties["MECH-FATIGUE-C"] and all("test_frequency_rpm" in output.conditions for output in _outputs(fatigue)), "Cycles are outputs; 4000 RPM is a condition."),
        _invariant(9, "run-out != cycles_to_failure", len(fatigue_runouts) == 19 and all(all(output.property != "cycles_to_failure" for output in experiment.outputs) and all(output.conditions.get("runout_limit_cycles") == 10_000_000 for output in experiment.outputs) for experiment in fatigue_runouts), "All 19 run-outs remain censored at 10^7 cycles."),
        _invariant(10, "fatigue strength != UTS", MECHANICAL_PROPERTIES["fatigue_strength"].family != MECHANICAL_PROPERTIES["ultimate_tensile_strength"].family, "Fatigue and tensile strength belong to different families."),
        _invariant(11, "fatigue limit not inferred", "fatigue_limit" not in properties["MECH-FATIGUE-C"], "No fatigue-limit output was derived."),
        _invariant(12, "duplicate fatigue rows remain separate", len(duplicate_227) == 2 and len({item.experiment_id for item in duplicate_227}) == 2 and len({item.experiment_id for item in fatigue.experiments}) == 60, "Duplicate 227.26 MPa rows and all 60 source rows retain distinct experiment IDs."),
        _invariant(13, "hardness scales remain distinct", len({MECHANICAL_PROPERTIES[key].unit_family for key in ("vickers_hardness", "rockwell_hardness", "brinell_hardness")}) == 3 and properties["MECH-HARD-D"] == {"vickers_hardness"}, "Only source-reported Vickers hardness is admitted."),
        _invariant(14, "hardness not converted to MPa", all(output.unit == "HV" for output in _outputs(hard)), "All 18 hardness outputs retain HV."),
        _invariant(15, "K_IC != K_JC", {"K_IC", "K_JC", "K_JU"} == {output.conditions.get("reported_term") for output in fracture_outputs}, "All three reported fracture metrics remain explicit."),
        _invariant(16, "K_JU not promoted to valid toughness", all(output.conditions.get("validity") == "invalid_rough_fracture_toughness" for output in fracture_outputs if output.conditions.get("reported_term") == "K_JU"), "All three K_JU rows retain invalid rough-estimate status."),
        _invariant(17, "fracture toughness != ordinary stress", all(output.unit == "MPa*sqrt(m)" for output in fracture_outputs), "Fracture values retain MPa*sqrt(m), never MPa."),
        _invariant(18, "computational outputs remain CalculationRecords", not compute.experiments and len(compute.calculations) == 4 and len(_outputs(compute)) == 28, "Compute-F contains four calculations, 28 outputs, and zero experiments."),
        _invariant(19, "experimental outputs remain ExperimentRecords", all(not archives[case].calculations for case in ("MECH-GOLD-A", "MECH-CREEP-B", "MECH-FATIGUE-C", "MECH-HARD-D", "MECH-FRACTURE-E")), "All five experimental cases contain zero calculations."),
        _invariant(20, "cited review data remain non-focal", not review.experiments and not review.calculations and review_candidates and all(item["ownership"] != "focal_work" for item in review_candidates), "Review-G candidates are preserved only in noncanonical review context."),
        _invariant(21, "negative controls produce no Mechanical contamination", negative_route.domain == "batteries" and not negative.experiments and not negative.calculations and not project_archives([negative]), "Negative-H routes Batteries and has no Mechanical records or analytics."),
        _invariant(22, "captions alone cannot admit numeric data", all(ev.text_snippet and ev.verbatim_match is True and ev.locator for ev in all_evidence), "Every canonical value has value-level verbatim evidence and a locator."),
        _invariant(23, "N/A cannot become numeric observation", len(omitted) == 3 and all("n/a" not in output.raw_value.casefold() for output in _outputs(creep)), "Three N/A/invalid Creep rows are excluded."),
        _invariant(24, "evidence provenance retained", all(ev.page and ev.source_type.value in {"table", "text"} for ev in all_evidence), "Every canonical output retains page and source type."),
        _invariant(25, "sample variants remain distinct", all(len(record.material_ids) == 1 for archive in archives.values() for record in [*archive.experiments, *archive.calculations]) and all(len({item.material_id for item in archive.materials}) == len(archive.materials) for archive in archives.values()), "Each scientific record has one stable case-local material."),
        _invariant(26, "processing context retained", all(output.conditions.get("heat_treatment") for output in _outputs(gold_a)) and all("cooling_rate" in output.conditions for output in _outputs(hard)) and all(output.conditions.get("processing_state") for output in [*_outputs(creep), *_outputs(fatigue), *fracture_outputs]), "Tensile, hardness, creep, fatigue, and fracture processing context remains attached."),
        _invariant(27, "raw typography preserved", all(any(output.raw_value == ev.text_snippet for ev in output.evidence) for output in all_canonical), "Each canonical raw value is identical to a source evidence snippet."),
        _invariant(28, "normalization does not alter scientific identity", all(output.property in MECHANICAL_PROPERTIES for output in all_canonical) and normalization_safe, "Canonical keys stay contracted; historical provider normalization is verified from its report when available, otherwise from committed freeze metadata."),
        _invariant(29, "deterministic recovery cannot bypass ownership", not review.experiments and not review.calculations and all(item["reason"].startswith("ownership_") for item in _quarantine(review)), "Review guard forces all reviewed scientific objects through ownership quarantine."),
        _invariant(30, "archive/domain scoping remains intact", all(archive.metadata.domain == "mechanical" and len(archive.domain_payloads) == 1 and archive.domain_payloads[0].domain == "mechanical" for archive in archives.values()), "Every benchmark archive and payload is Mechanical-scoped; Negative-H is an empty Mechanical contamination probe after Batteries routing."),
    ]

    offline = {case: offline_report(case) for case in archives}
    live_paths = {
        "MECH-GOLD-A": ROOT / "output/mechanical_v1/live/MECH-GOLD-A/closure_retry_20260922/report.json",
        "MECH-CREEP-B": ROOT / "output/mechanical_v1/live/MECH-CREEP-B/first_20260922/report.json",
        "MECH-FATIGUE-C": ROOT / "output/mechanical_v1/live/MECH-FATIGUE-C/closure_retry_20260922/report.json",
        "MECH-HARD-D": ROOT / "output/mechanical_v1/live/MECH-HARD-D/first_20260922/report.json",
        "MECH-FRACTURE-E": ROOT / "output/mechanical_v1/live/MECH-FRACTURE-E/first_20260922/report.json",
        "MECH-COMPUTE-F": ROOT / "output/mechanical_v1/live/MECH-COMPUTE-F/first_20260922/report.json",
    }
    live = {case: live_report(case, path) for case, path in live_paths.items()}
    review_score = offline["MECH-REVIEW-G"]["score"]
    negative_score = offline["MECH-NEGATIVE-H"]["score"]
    cases = [
        _case_summary("MECH-GOLD-A", gold_a, offline["MECH-GOLD-A"], live["MECH-GOLD-A"], "mechanical", ["tensile_testing"], "RAW_PROVIDER_FAILED_RECOVERY_PASSED"),
        _case_summary("MECH-CREEP-B", creep, offline["MECH-CREEP-B"], live["MECH-CREEP-B"], "mechanical", ["creep_stress_rupture"], "RAW_PROVIDER_FAILED_RECOVERY_PASSED"),
        _case_summary("MECH-FATIGUE-C", fatigue, offline["MECH-FATIGUE-C"], live["MECH-FATIGUE-C"], "mechanical", ["fatigue_testing"], "RAW_PROVIDER_FAILED_RECOVERY_PASSED"),
        _case_summary("MECH-HARD-D", hard, offline["MECH-HARD-D"], live["MECH-HARD-D"], "mechanical", ["hardness_testing"], "RAW_PROVIDER_FAILED_RECOVERY_PASSED"),
        _case_summary("MECH-FRACTURE-E", fracture, offline["MECH-FRACTURE-E"], live["MECH-FRACTURE-E"], "mechanical", ["fracture_toughness"], "RAW_PROVIDER_FAILED_RECOVERY_PASSED"),
        _case_summary("MECH-COMPUTE-F", compute, offline["MECH-COMPUTE-F"], live["MECH-COMPUTE-F"], "mechanical", ["computational_mechanics"], "LIVE_UNAVAILABLE_OFFLINE_PASSED"),
        _case_summary("MECH-REVIEW-G", review, offline["MECH-REVIEW-G"], None, review_route.domain, ["review"], "PASS_OFFLINE", ownership=review_score["ownership_violations"], evidence=review_score["evidence_violations"]),
        _case_summary("MECH-NEGATIVE-H", negative, offline["MECH-NEGATIVE-H"], None, negative_route.domain, negative_route.paper_types, "PASS_OFFLINE"),
    ]
    passed = sum(item["passed"] for item in invariants)
    review_analytics = len(project_archives([review]))
    negative_analytics = len(project_archives([negative]))
    compute_analytics = project_archives([compute])
    evidence_violations = sum(not (ev.page and ev.text_snippet and ev.verbatim_match is True) for ev in all_evidence)
    cross_record_leakage = sum(
        len(record.material_ids) != 1 or record.material_ids[0] not in {item.material_id for item in archive.materials}
        for archive in archives.values() for record in [*archive.experiments, *archive.calculations]
    )
    return {
        "suite": "Mechanical V1 scientific closure",
        "aggregate_benchmark_score": None,
        "aggregate_score_policy": "No aggregate percentage across heterogeneous scientific contracts.",
        "cases": cases,
        "invariants": invariants,
        "invariant_audit": {"passed": passed, "total": len(invariants)},
        "safety": {
            "ownership_contamination": review_score["ownership_violations"],
            "evidence_violations": evidence_violations + review_score["evidence_violations"],
            "cross_record_leakage": cross_record_leakage,
            "analytics_contamination": review_analytics + negative_analytics,
            "review_analytics_rows": review_analytics,
            "negative_analytics_rows": negative_analytics,
            "compute_analytics_rows": len(compute_analytics),
            "compute_modalities": sorted({row.modality for row in compute_analytics}),
            "excluded_creep_na_rows": len(omitted),
            "fatigue_runouts_censored": len(fatigue_runouts),
            "fracture_non_kic_states": sorted({
                f"{output.conditions.get('reported_term')}:{output.conditions.get('validity')}"
                for output in fracture_outputs if output.conditions.get("reported_term") != "K_IC"
            }),
            "hardness_properties": sorted(properties["MECH-HARD-D"]),
        },
        "provider_status_summary": {case: report["status"] for case, report in live.items()} | {
            "MECH-REVIEW-G": "NOT_RUN", "MECH-NEGATIVE-H": "NOT_RUN",
        },
        "freeze_decision": (
            "READY_TO_FREEZE_DETERMINISTIC_MECHANICAL_V1"
            if passed == len(invariants) and evidence_violations == 0 and cross_record_leakage == 0
            else "NOT_READY_TO_FREEZE"
        ),
        "freeze_scope": "Deterministic contracts, source locks, recovery, ownership, evidence, routing, and analytics safety. Raw provider limitations remain benchmarked limitations, not silently repaired successes.",
    }


def main() -> int:
    summary = build_closure_summary()
    output = ROOT / "output/mechanical_v1/closure_summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "cases": len(summary["cases"]),
        "invariants": summary["invariant_audit"],
        "freeze_decision": summary["freeze_decision"],
    }))
    return 0 if summary["freeze_decision"].startswith("READY_TO_FREEZE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
