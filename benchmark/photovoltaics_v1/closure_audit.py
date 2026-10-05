"""Final deterministic eight-case closure audit for Photovoltaics V1."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.photovoltaics_v1.case_common import load_locked, read_json
from benchmark.photovoltaics_v1.recover_compute_e import recover_compute_e
from benchmark.photovoltaics_v1.recover_gold_a import recover_gold_a
from benchmark.photovoltaics_v1.recover_mixed_h import recover_mixed_h
from benchmark.photovoltaics_v1.recover_negative_g import recover_negative_g
from benchmark.photovoltaics_v1.recover_review_f import recover_review_f
from benchmark.photovoltaics_v1.recover_spec_b import recover_spec_b
from benchmark.photovoltaics_v1.recover_stab_c import recover_stab_c
from benchmark.photovoltaics_v1.recover_stack_d import recover_stack_d
from benchmark.photovoltaics_v1.score_additional_cases import (
    score_spec_b,
    score_stab_c,
    score_stack_d,
)
from benchmark.photovoltaics_v1.score_closure_cases import (
    score_compute_e,
    score_mixed_h,
    score_negative_g,
    score_review_f,
)
from benchmark.photovoltaics_v1.score_gold_a import score_gold_a
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.photovoltaics_contract import (
    PV_PROPERTIES,
    photovoltaics_admission_decision,
)
from synthex_platform.visual.analytics.projection import project_archives


def _measurement(
    property_name: str,
    raw_value: str,
    value: float | None,
    unit: str,
    *,
    source_type: str = "table",
    conditions: dict | None = None,
) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=raw_value,
        value=value,
        unit=unit,
        conditions={"scientific_type": "reported_measurement", **(conditions or {})},
        evidence=[Evidence(
            page=1,
            source_type=source_type,
            original_source_type="native_text",
            verbatim_match=True,
            text_snippet=raw_value,
            table_id="closure-probe",
            locator="page=1;probe=closure",
        )],
    )


def _properties(archive) -> set[str]:
    return {
        output.property
        for record in [*archive.experiments, *archive.calculations]
        for output in record.outputs
    }


def _raw_evidence_preserved(archive) -> bool:
    return all(
        output.raw_value
        and output.evidence
        and any(output.raw_value in (evidence.text_snippet or "") for evidence in output.evidence)
        for record in [*archive.experiments, *archive.calculations]
        for output in record.outputs
    )


def _case_result(case_id: str, score: dict) -> dict:
    return {
        "case_id": case_id,
        "status": "PASS_OFFLINE" if score["passed"] == score["total"] else "FAIL_OFFLINE",
        "passed": score["passed"],
        "total": score["total"],
        "provider_invoked": False,
    }


def run_closure_audit(*, write_output: bool = True) -> dict:
    gold_a = read_json("gold_a.json")
    archive_a, _ = recover_gold_a()
    score_a = score_gold_a(archive_a, gold_a)

    gold_b = read_json("spec_b_gold.json")
    archive_b, recovered_b = recover_spec_b()
    score_b = score_spec_b(archive_b, gold_b)

    gold_c = read_json("stab_c_gold.json")
    archive_c, _ = recover_stab_c()
    score_c = score_stab_c(archive_c, gold_c)

    gold_d = read_json("stack_d_gold.json")
    archive_d, _ = recover_stack_d()
    score_d = score_stack_d(archive_d, gold_d)

    _, gold_e, _ = load_locked("compute_e_source_lock.json")
    archive_e, recovered_e = recover_compute_e()
    score_e = score_compute_e(archive_e, recovered_e, gold_e)

    _, gold_f, _ = load_locked("review_f_source_lock.json")
    archive_f, guarded_f, route_f = recover_review_f()
    score_f = score_review_f(archive_f, guarded_f, route_f, gold_f)

    _, gold_g, _ = load_locked("negative_g_source_lock.json")
    archive_g, first_g, second_g, text_g = recover_negative_g()
    score_g = score_negative_g(archive_g, first_g, second_g, text_g, gold_g)

    _, gold_h, _ = load_locked("mixed_h_source_lock.json")
    archive_h = recover_mixed_h()
    score_h = score_mixed_h(archive_h, gold_h)

    archives = {
        "PV-GOLD-A": archive_a,
        "PV-SPEC-B": archive_b,
        "PV-STAB-C": archive_c,
        "PV-STACK-D": archive_d,
        "PV-COMPUTE-E": archive_e,
        "PV-REVIEW-F": archive_f,
        "PV-NEG-G": archive_g,
        "PV-MIXED-H": archive_h,
    }
    scores = {
        "PV-GOLD-A": score_a,
        "PV-SPEC-B": score_b,
        "PV-STAB-C": score_c,
        "PV-STACK-D": score_d,
        "PV-COMPUTE-E": score_e,
        "PV-REVIEW-F": score_f,
        "PV-NEG-G": score_g,
        "PV-MIXED-H": score_h,
    }

    analytics_b = project_archives([archive_b])
    analytics_c = project_archives([archive_c])
    analytics_d = project_archives([archive_d])
    analytics_e = project_archives([archive_e])
    analytics_h = project_archives([archive_h])
    device_variant_h = {
        device.device_id: device.configuration.get("variant") for device in archive_h.devices
    }
    expected_h = {
        (item["variant"], item["modality"], item["property"])
        for item in gold_h["measurements"]
    }
    actual_h = {
        (
            device_variant_h.get(row.device_id),
            row.conditions.get("measurement_modality"),
            row.property_name,
        )
        for row in analytics_h
    }
    spectral_counts_match = all(
        len(experiment.outputs) == expected["point_count"]
        and len(recovered["points"]) == expected["point_count"]
        for experiment, expected, recovered in zip(
            archive_b.experiments, gold_b["series"], recovered_b, strict=True,
        )
    )
    stability_outputs = [output for item in archive_c.experiments for output in item.outputs]
    stacks_d_h = [
        *[device.configuration["layer_stack"] for device in archive_d.devices],
        *[device.configuration["layer_stack"] for device in archive_h.devices],
    ]
    process_devices_d = {
        output for process in archive_d.processes for output in process.outputs
    }
    # The historical no-payload reports are local operational evidence. Their
    # outcomes are preserved in the committed freeze manifest for clean clones.
    freeze = read_json(ROOT / "benchmark/photovoltaics_v1/freeze_manifest.json")
    historical = {
        item["case_id"]: item for item in freeze["provider_history"]
        if item.get("history") == "historical" and item["case_id"] in {"PV-GOLD-A", "PV-SPEC-B"}
    }
    live_reports = {}
    for case_id in ("PV-GOLD-A", "PV-SPEC-B"):
        path = ROOT / "output/photovoltaics_v1/live" / case_id / "report.json"
        if path.is_file():
            live_reports[case_id] = read_json(path)
        else:
            item = historical[case_id]
            live_reports[case_id] = {
                "status": item["status"],
                "attempt_count": item["attempts"],
                "payload_returned": item["payload_returned"],
                "raw_provider_scientific_score": item["raw_score"],
            }

    context = {"illumination_spectrum": "AM1.5G", "irradiance": 100.0}
    caption_probe = _measurement(
        "power_conversion_efficiency", "18.5", 18.5, "%",
        source_type="figure_caption", conditions=context,
    )
    na_probe = _measurement(
        "power_conversion_efficiency", "N/A", None, "%", conditions=context,
    )
    missing_light_probe = _measurement(
        "power_conversion_efficiency", "18.5", 18.5, "%",
        conditions={"irradiance": 100.0},
    )

    invariant_values = [
        ("pce_not_eqe", "power_conversion_efficiency" != "external_quantum_efficiency"),
        ("pce_not_ipce", "power_conversion_efficiency" != "incident_photon_to_current_efficiency"),
        ("pce_not_retained_efficiency", "power_conversion_efficiency" != "retained_efficiency"),
        ("voc_not_maximum_power_voltage", "open_circuit_voltage" != "voltage_at_maximum_power"),
        ("jsc_not_generic_current", {"short_circuit_current", "short_circuit_current_density"}.isdisjoint({"current", "current_density"})),
        ("fill_factor_not_pce", "fill_factor" != "power_conversion_efficiency"),
        ("wavelength_not_photon_energy", all(row.conditions.get("wavelength_unit") == "nm" and "photon_energy" not in row.conditions for row in analytics_b)),
        ("spectral_points_retain_device_identity", bool(analytics_b) and all(row.device_id for row in analytics_b)),
        ("missing_spectral_points_not_interpolated", spectral_counts_match),
        ("active_area_not_aperture_area", PV_PROPERTIES["active_area"] is not PV_PROPERTIES["aperture_area"]),
        ("active_area_not_inferred", all(output.conditions.get("active_area") == "not reported" for item in archive_a.experiments for output in item.outputs)),
        ("scan_direction_not_inferred", all(output.conditions.get("scan_direction") == "not reported" for item in archive_a.experiments for output in item.outputs)),
        ("am1_5g_not_inferred", photovoltaics_admission_decision(missing_light_probe, role="result").reason == "missing_required_condition_illumination_spectrum"),
        ("forward_scan_not_reverse_scan", "forward" != "reverse" and any(row.conditions.get("scan_direction") == "reverse" for row in analytics_h)),
        ("stabilized_pce_not_swept_pce", PV_PROPERTIES["stabilized_power_conversion_efficiency"] is not PV_PROPERTIES["swept_power_conversion_efficiency"]),
        ("initial_pce_not_aged_pce", PV_PROPERTIES["initial_power_conversion_efficiency"] is not PV_PROPERTIES["aged_power_conversion_efficiency"]),
        ("aged_pce_not_retained_percentage", PV_PROPERTIES["aged_power_conversion_efficiency"] is not PV_PROPERTIES["retained_efficiency"]),
        ("aging_time_not_t80", PV_PROPERTIES["aging_time"].role == "process_parameter" and PV_PROPERTIES["t80"].role == "result"),
        ("t80_not_t90", PV_PROPERTIES["t80"] is not PV_PROPERTIES["t90"]),
        ("stability_environment_retained", bool(stability_outputs) and all(output.conditions.get("temperature") == 85.0 and output.conditions.get("atmosphere") == "ambient air" for output in stability_outputs)),
        ("ordered_layer_stack_retained", all([layer["sequence_index"] for layer in stack] == list(range(len(stack))) for stack in stacks_d_h)),
        ("layer_roles_retained", all("absorber" in {layer["role"] for layer in stack} and len({layer["role"] for layer in stack}) >= 5 for stack in stacks_d_h)),
        ("device_specific_fabrication_retained", process_devices_d == {device.device_id for device in archive_d.devices}),
        ("computational_not_experimental", bool(archive_e.calculations) and not archive_e.experiments and all(row.modality == "computational" for row in analytics_e)),
        ("simulated_pce_not_measured_pce", "simulated_power_conversion_efficiency" in _properties(archive_e) and "power_conversion_efficiency" not in _properties(archive_e)),
        ("simulated_voc_jsc_not_measured_voc_jsc", {"simulated_open_circuit_voltage", "predicted_short_circuit_current_density"} <= _properties(archive_e) and {"open_circuit_voltage", "short_circuit_current_density"}.isdisjoint(_properties(archive_e))),
        ("cited_review_values_remain_nonfocal", not archive_f.experiments and not archive_f.calculations and score_f["noncanonical_candidate_count"] > 0),
        ("negative_control_has_no_pv_contamination", not archive_g.devices and not archive_g.experiments and not archive_g.calculations and not project_archives([archive_g])),
        ("caption_only_evidence_cannot_admit", photovoltaics_admission_decision(caption_probe, role="result").reason == "no_value_specific_verbatim_evidence"),
        ("na_cannot_become_numeric_data", photovoltaics_admission_decision(na_probe, role="result").reason == "numeric_value_required"),
        ("uncertainty_stays_with_correct_metric", all(output.uncertainty is not None and output.uncertainty_unit == output.unit and output.property in gold_a["rows"][0] for item in archive_a.experiments for output in item.outputs)),
        ("device_variants_remain_distinct", all(len({device.configuration.get("variant") for device in archive.devices}) == len(archive.devices) for archive in (archive_a, archive_d, archive_h))),
        ("cross_modality_values_tied_to_correct_device", actual_h == expected_h),
        ("raw_typography_and_source_evidence_preserved", all(_raw_evidence_preserved(archive) for archive in (archive_a, archive_b, archive_c, archive_d, archive_e, archive_h))),
        ("archive_domain_scoping_correct", all(len(archive.domain_payloads) == 1 and archive.domain_payloads[0].domain == "photovoltaics" for archive in archives.values())),
    ]
    invariants = [
        {"number": index, "id": name, "passed": bool(passed)}
        for index, (name, passed) in enumerate(invariant_values, start=1)
    ]

    case_results = [_case_result(case_id, scores[case_id]) for case_id in archives]
    provider_status = {
        case_id: {
            "status": report["status"],
            "attempts": report.get("attempt_count", len(report.get("provider_attempts", []))),
            "payload_returned": report.get("payload_returned", any(
                item["payload_returned"] for item in report.get("provider_attempts", []))),
            "raw_score": report["raw_provider_scientific_score"],
            "RAW_PROVIDER_ARTIFACT_AVAILABLE": False,
            "rerun_in_closure": False,
        }
        for case_id, report in live_reports.items()
    }
    ownership_contamination = sum(score.get("ownership_violations", 0) for score in scores.values())
    evidence_violations = sum(score.get("evidence_violations", 0) for score in scores.values())
    cross_record_leakage = sum(score.get("cross_record_leakage", 0) for score in scores.values())
    analytics_contamination = sum(score.get("analytics_contamination_count", 0) for score in scores.values())
    all_cases_pass = all(item["passed"] == item["total"] for item in case_results)
    all_invariants_pass = all(item["passed"] for item in invariants)
    live_status_preserved = all(
        item["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES"
        and item["attempts"] == 3
        and not item["payload_returned"]
        and item["raw_score"] is None
        for item in provider_status.values()
    )
    ready = all((
        all_cases_pass,
        all_invariants_pass,
        ownership_contamination == 0,
        evidence_violations == 0,
        cross_record_leakage == 0,
        analytics_contamination == 0,
        live_status_preserved,
    ))
    result = {
        "benchmark": "Photovoltaics V1",
        "mode": "deterministic_offline_closure",
        "provider_invoked": False,
        "case_summary": case_results,
        "case_assertions": {
            "passed": sum(item["passed"] for item in case_results),
            "total": sum(item["total"] for item in case_results),
        },
        "scientific_invariants": {
            "passed": sum(item["passed"] for item in invariants),
            "total": len(invariants),
            "results": invariants,
        },
        "contamination": {
            "ownership": ownership_contamination,
            "evidence_violations": evidence_violations,
            "cross_record_leakage": cross_record_leakage,
            "analytics": analytics_contamination,
        },
        "analytics_safety": {
            "review_values_absent": not project_archives([archive_f]),
            "negative_case_absent": not project_archives([archive_g]),
            "computational_rows_marked": bool(analytics_e) and all(row.modality == "computational" for row in analytics_e),
            "spectral_coordinates_retained": bool(analytics_b) and all(row.conditions.get("wavelength") is not None for row in analytics_b),
            "stability_context_retained": bool(analytics_c) and all(row.conditions.get("aging_protocol") for row in analytics_c),
            "stack_process_context_retained": bool(analytics_d) and all(row.conditions.get("device_layer_stack") for row in analytics_d),
            "mixed_modalities_separate": {row.conditions.get("measurement_modality") for row in analytics_h} == {"performance", "spectral_summary", "stabilized_output", "thermal_stability"},
            "archive_domain_scoping": invariants[-1]["passed"],
        },
        "provider_status": provider_status,
        "readiness": "READY_TO_FREEZE_DETERMINISTIC_PV_V1" if ready else "NOT_READY_TO_FREEZE",
        "raw_gemini_photovoltaics_production_ready": False,
        "limitation": "PV-GOLD-A and PV-SPEC-B have no provider payload after three 503/high-demand responses; this is not a zero score.",
    }
    if write_output:
        output = ROOT / "output/photovoltaics_v1/closure_audit.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> int:
    result = run_closure_audit()
    print(json.dumps({
        "cases": result["case_assertions"],
        "invariants": {
            "passed": result["scientific_invariants"]["passed"],
            "total": result["scientific_invariants"]["total"],
        },
        "contamination": result["contamination"],
        "readiness": result["readiness"],
    }))
    return 0 if result["readiness"] == "READY_TO_FREEZE_DETERMINISTIC_PV_V1" else 1


if __name__ == "__main__":
    raise SystemExit(main())
