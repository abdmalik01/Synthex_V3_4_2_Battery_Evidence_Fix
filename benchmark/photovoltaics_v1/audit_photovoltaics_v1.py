"""Twenty-five invariant audit for the four Photovoltaics V1 benchmark cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.photovoltaics_contract import PV_PROPERTIES, photovoltaics_admission_decision
from synthex_platform.visual.analytics.projection import project_archives

from benchmark.photovoltaics_v1.case_common import read_json
from benchmark.photovoltaics_v1.recover_gold_a import recover_gold_a
from benchmark.photovoltaics_v1.recover_spec_b import recover_spec_b
from benchmark.photovoltaics_v1.recover_stab_c import recover_stab_c
from benchmark.photovoltaics_v1.recover_stack_d import recover_stack_d
from benchmark.photovoltaics_v1.score_additional_cases import score_spec_b, score_stab_c, score_stack_d
from benchmark.photovoltaics_v1.score_gold_a import score_gold_a


def _outputs(archive):
    return [output for experiment in archive.experiments for output in experiment.outputs]


def _contiguous_stacks(archive) -> bool:
    return all(
        [layer["sequence_index"] for layer in device.configuration["layer_stack"]]
        == list(range(len(device.configuration["layer_stack"])))
        for device in archive.devices
    )


def audit_photovoltaics_v1() -> dict:
    gold_a = read_json("gold_a.json")
    spec_gold = read_json("spec_b_gold.json")
    stab_gold = read_json("stab_c_gold.json")
    stack_gold = read_json("stack_d_gold.json")
    archive_a, _ = recover_gold_a()
    archive_b, recovered_b = recover_spec_b()
    archive_c, _ = recover_stab_c()
    archive_d, _ = recover_stack_d()
    score_a = score_gold_a(archive_a, gold_a)
    score_b = score_spec_b(archive_b, spec_gold)
    score_c = score_stab_c(archive_c, stab_gold)
    score_d = score_stack_d(archive_d, stack_gold)
    outputs_a, outputs_b, outputs_c, outputs_d = map(_outputs, (archive_a, archive_b, archive_c, archive_d))
    expected_properties = {
        "PV-GOLD-A": {"open_circuit_voltage", "short_circuit_current", "short_circuit_current_density", "fill_factor", "power_conversion_efficiency"},
        "PV-SPEC-B": {"external_quantum_efficiency"},
        "PV-STAB-C": {"t80", "retained_efficiency"},
        "PV-STACK-D": {"open_circuit_voltage", "short_circuit_current_density", "fill_factor", "power_conversion_efficiency"},
    }
    caption_only = Measurement(
        property="power_conversion_efficiency", raw_value="19.0", value=19.0, unit="%",
        conditions={"scientific_type": "reported_measurement", "illumination_spectrum": "AM1.5G", "irradiance": 100.0},
        evidence=[Evidence(page=1, source_type="figure_caption", verbatim_match=True, text_snippet="19.0", locator="figure=1")],
    )
    na_value = Measurement(
        property="power_conversion_efficiency", raw_value="N/A", value=None, unit="%",
        conditions={"scientific_type": "reported_measurement", "illumination_spectrum": "AM1.5G", "irradiance": 100.0},
        evidence=[Evidence(page=1, source_type="table", verbatim_match=True, text_snippet="N/A", table_id="t", locator="row=1;column=PCE")],
    )
    archives = (archive_a, archive_b, archive_c, archive_d)
    quarantine_count = sum(
        len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])
        for archive in archives
    )
    evidence_violations = sum(
        not output.raw_value
        or not output.evidence
        or not any(
            evidence.verbatim_match is True
            and output.raw_value.casefold() in (evidence.text_snippet or "").casefold()
            and (evidence.locator or evidence.table_id)
            for evidence in output.evidence
        )
        for archive in archives for output in _outputs(archive)
    )
    cross_record_leakage = sum(
        not assertion["passed"]
        for score in (score_a, score_b, score_c, score_d)
        for assertion in score["assertions"]
    )
    analytic_rows = [row for archive in archives for row in project_archives([archive])]
    analytics_contamination = int(
        len(analytic_rows) != 274
        or any(not row.device_id for row in analytic_rows)
        or any(row.property_name not in set().union(*expected_properties.values()) for row in analytic_rows)
    )
    invariants = [
        ("01_pce_is_not_eqe", PV_PROPERTIES["power_conversion_efficiency"] is not PV_PROPERTIES["external_quantum_efficiency"] and not ({item.property for item in outputs_b} & {"power_conversion_efficiency"})),
        ("02_pce_is_not_ipce", PV_PROPERTIES["power_conversion_efficiency"] is not PV_PROPERTIES["incident_photon_to_current_efficiency"]),
        ("03_pce_is_not_retained_efficiency", PV_PROPERTIES["power_conversion_efficiency"] is not PV_PROPERTIES["retained_efficiency"] and {item.property for item in outputs_c} == {"t80", "retained_efficiency"}),
        ("04_voc_is_not_maximum_power_voltage", PV_PROPERTIES["open_circuit_voltage"] is not PV_PROPERTIES["voltage_at_maximum_power"]),
        ("05_jsc_is_not_generic_current", all(PV_PROPERTIES["short_circuit_current_density"] is not PV_PROPERTIES[key] for key in ("current_density", "short_circuit_current"))),
        ("06_fill_factor_is_not_efficiency", PV_PROPERTIES["fill_factor"] is not PV_PROPERTIES["power_conversion_efficiency"]),
        ("07_wavelength_is_not_photon_energy", all("photon_energy" not in item.conditions for item in outputs_b) and all(item.conditions.get("wavelength_unit") == "nm" for item in outputs_b)),
        ("08_eqe_series_points_retain_device_identity", len(outputs_b) == 223 and all(experiment.device_id for experiment in archive_b.experiments) and len({item.conditions.get("series_id") for item in outputs_b}) == 3),
        ("09_missing_wavelengths_are_not_interpolated", [len(item["points"]) for item in recovered_b] == [71, 81, 71] and all(item.conditions["wavelength"] <= 1000 for item in archive_b.experiments[0].outputs + archive_b.experiments[2].outputs)),
        ("10_active_area_is_not_aperture_area", PV_PROPERTIES["active_area"] is not PV_PROPERTIES["aperture_area"]),
        ("11_active_area_not_inferred", all(item.conditions.get("active_area") == "not reported" for item in outputs_a)),
        ("12_scan_direction_not_inferred", all(item.conditions.get("scan_direction") == "not reported" for item in outputs_a)),
        ("13_am1_5g_not_inferred", all("illumination_spectrum" not in item.conditions for item in outputs_b + outputs_c)),
        ("14_forward_scan_is_not_reverse_scan", all(item.conditions.get("scan_direction") == "forward and reverse measured; Table 1 direction not specified" for item in outputs_d)),
        ("15_stabilized_pce_is_not_swept_pce", PV_PROPERTIES["stabilized_power_conversion_efficiency"] is not PV_PROPERTIES["swept_power_conversion_efficiency"]),
        ("16_initial_pce_is_not_aged_pce", PV_PROPERTIES["initial_power_conversion_efficiency"] is not PV_PROPERTIES["aged_power_conversion_efficiency"] and not ({"initial_power_conversion_efficiency", "aged_power_conversion_efficiency"} & {item.property for item in outputs_c})),
        ("17_aging_time_is_not_t80", all(item.property != "aging_time" for item in outputs_c) and all(item.conditions.get("aging_time") is None for item in outputs_c if item.property == "t80")),
        ("18_t80_is_not_t90", PV_PROPERTIES["t80"] is not PV_PROPERTIES["t90"] and {item.property for item in outputs_c}.isdisjoint({"t90"})),
        ("19_aging_environment_retained", all(item.conditions.get("aging_protocol") == "ISOS-D-2" and item.conditions.get("temperature") == 85.0 and item.conditions.get("atmosphere") == "ambient air" for item in outputs_c)),
        ("20_ordered_layer_stack_retained", all(_contiguous_stacks(archive) for archive in archives)),
        ("21_layer_role_retained", all(layer.get("role") for archive in archives for device in archive.devices for layer in device.configuration["layer_stack"])),
        ("22_device_specific_processing_retained", score_d["passed"] == score_d["total"] == 6 and len({(device.configuration["pc70bm_thickness_nm"], str(device.configuration["n_dmbi_wt_percent"])) for device in archive_d.devices}) == 6),
        ("23_caption_only_evidence_cannot_admit_values", photovoltaics_admission_decision(caption_only, role="result").reason == "no_value_specific_verbatim_evidence"),
        ("24_na_cannot_become_numeric_data", photovoltaics_admission_decision(na_value, role="result").reason == "numeric_value_required"),
        ("25_archive_and_domain_scoping_remain_correct", all(archive.metadata.domain == "photovoltaics" and len(archive.domain_payloads) == 1 and archive.domain_payloads[0].domain == "photovoltaics" for archive in archives)),
    ]
    result = {
        "audit": "Photovoltaics V1 four-case invariant audit",
        "total": len(invariants),
        "passed": sum(passed for _, passed in invariants),
        "failed": [name for name, passed in invariants if not passed],
        "invariants": [{"name": name, "passed": bool(passed)} for name, passed in invariants],
        "contamination": {
            "ownership_contamination": quarantine_count,
            "evidence_violations": evidence_violations,
            "cross_record_leakage": cross_record_leakage,
            "analytics_contamination": analytics_contamination,
        },
    }
    if result["total"] != 25:
        raise AssertionError(f"Audit definition drifted to {result['total']} invariants")
    return result


def main() -> int:
    result = audit_photovoltaics_v1()
    out = ROOT / "output" / "photovoltaics_v1" / "offline" / "four_case_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "total": result["total"], "failed": result["failed"]}))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
