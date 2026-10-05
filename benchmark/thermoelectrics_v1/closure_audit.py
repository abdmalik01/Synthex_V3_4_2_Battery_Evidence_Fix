"""Eight-case Thermoelectrics V1 scientific closure and 40-invariant audit."""

from __future__ import annotations

import json

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.thermoelectrics_contract import (
    TE_PROPERTIES, thermoelectrics_admission_decision,
)
from synthex_platform.visual.analytics.projection import project_archives

from benchmark.thermoelectrics_v1.recover_closure import (
    CASE_DIR, recover_compute_e, recover_mixed_h, recover_neg_g, recover_review_f,
)
from benchmark.thermoelectrics_v1.recover_expansion import (
    recover_aniso_d, recover_derived_c, recover_series_b,
)
from benchmark.thermoelectrics_v1.recover_gold_a import recover_gold_a
from benchmark.thermoelectrics_v1.score_closure import (
    score_compute_e, score_mixed_h, score_neg_g, score_review_f,
)
from benchmark.thermoelectrics_v1.score_expansion import (
    score_aniso_d, score_derived_c, score_series_b,
)
from benchmark.thermoelectrics_v1.score_gold_a import score_gold_a


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _outputs(archive) -> list:
    return [output for record in [*archive.experiments, *archive.calculations] for output in record.outputs]


def _quarantine(archive) -> list:
    return archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def _probe_measurement(raw_value: str, value: float, *, caption: bool = False) -> Measurement:
    return Measurement(
        property="electrical_conductivity", raw_value=raw_value, value=value, unit="S/m",
        conditions={
            "scientific_type": "reported_measurement", "temperature": 300.0,
            "temperature_unit": "K", "measurement_orientation": "not_reported",
        },
        evidence=[Evidence(
            page=1, source_type=SourceType.text,
            original_source_type="figure_caption" if caption else "publisher_pdf",
            verbatim_match=True, text_snippet=f"conductivity {raw_value} S/m",
            locator="page=1;caption" if caption else "page=1;results",
        )],
    )


def build_closure_audit() -> dict:
    gold_a_archive, _ = recover_gold_a()
    series_archive, _ = recover_series_b()
    derived_archive, _, validation = recover_derived_c()
    aniso_archive, _ = recover_aniso_d()
    compute_archive = recover_compute_e()
    review_archive, cited_rows = recover_review_f()
    negative_archive, first_route, second_route, source_text = recover_neg_g()
    mixed_archive = recover_mixed_h()

    archives = {
        "TE-GOLD-A": gold_a_archive,
        "TE-SERIES-B": series_archive,
        "TE-DERIVED-C": derived_archive,
        "TE-ANISO-D": aniso_archive,
        "TE-COMPUTE-E": compute_archive,
        "TE-REVIEW-F": review_archive,
        "TE-NEG-G": negative_archive,
        "TE-MIXED-H": mixed_archive,
    }
    reports = {
        "TE-GOLD-A": score_gold_a(gold_a_archive, _read("gold_a.json")),
        "TE-SERIES-B": score_series_b(series_archive, _read("gold_series_b.json")),
        "TE-DERIVED-C": score_derived_c(derived_archive, _read("gold_derived_c.json"), validation),
        "TE-ANISO-D": score_aniso_d(aniso_archive, _read("gold_aniso_d.json")),
        "TE-COMPUTE-E": score_compute_e(compute_archive, _read("gold_compute_e.json")),
        "TE-REVIEW-F": score_review_f(review_archive, _read("gold_review_f.json"), cited_rows),
        "TE-NEG-G": score_neg_g(negative_archive, _read("gold_neg_g.json"), first_route, second_route, source_text),
        "TE-MIXED-H": score_mixed_h(mixed_archive, _read("gold_mixed_h.json")),
    }
    canonical_archives = [archive for case_id, archive in archives.items() if case_id not in {"TE-REVIEW-F", "TE-NEG-G"}]
    experimental_outputs = [output for archive in canonical_archives for record in archive.experiments for output in record.outputs]
    calculated_outputs = [output for archive in canonical_archives for record in archive.calculations for output in record.outputs]
    all_outputs = experimental_outputs + calculated_outputs
    analytics = project_archives(canonical_archives)
    all_records = [record for archive in canonical_archives for record in [*archive.experiments, *archive.calculations]]
    property_names = {output.property for output in all_outputs}
    seebeck = [output for output in all_outputs if output.property == "seebeck_coefficient"]
    temperatures = [output.conditions.get("temperature") for output in all_outputs if TE_PROPERTIES[output.property].requires_temperature]
    series_report = reports["TE-SERIES-B"]
    gold_report = reports["TE-GOLD-A"]
    mixed_report = reports["TE-MIXED-H"]
    review_report = reports["TE-REVIEW-F"]
    negative_report = reports["TE-NEG-G"]
    caption_rejected = not thermoelectrics_admission_decision(
        _probe_measurement("12.0", 12.0, caption=True), role="result"
    ).admitted
    na_rejected = not thermoelectrics_admission_decision(
        _probe_measurement("N/A", 0.0), role="result"
    ).admitted

    invariants = {
        "01_seebeck_not_voltage": "seebeck_coefficient" in property_names and "voltage" not in property_names,
        "02_seebeck_sign_preserved": bool(seebeck) and all(
            output.conditions.get("seebeck_sign") == ("positive" if output.value > 0 else "negative" if output.value < 0 else "zero")
            and output.conditions.get("absolute_value") is False for output in seebeck
        ),
        "03_electrical_conductivity_not_thermal_conductivity": TE_PROPERTIES["electrical_conductivity"].unit_family != TE_PROPERTIES["total_thermal_conductivity"].unit_family,
        "04_resistivity_not_conductivity": TE_PROPERTIES["electrical_resistivity"].unit_family != TE_PROPERTIES["electrical_conductivity"].unit_family,
        "05_total_kappa_not_lattice_kappa": {"total_thermal_conductivity", "lattice_thermal_conductivity"}.issubset(property_names),
        "06_total_kappa_not_electronic_kappa": "electronic_thermal_conductivity" in property_names and TE_PROPERTIES["total_thermal_conductivity"] is not TE_PROPERTIES["electronic_thermal_conductivity"],
        "07_lattice_kappa_not_electronic_kappa": {"lattice_thermal_conductivity", "electronic_thermal_conductivity"}.issubset(property_names),
        "08_power_factor_not_zt": {"power_factor", "zt"}.issubset(property_names) and TE_PROPERTIES["power_factor"].unit_family != TE_PROPERTIES["zt"].unit_family,
        "09_power_factor_not_efficiency": "power_factor" in property_names and "efficiency" not in TE_PROPERTIES,
        "10_zt_dimensionless": all(output.unit == "dimensionless" for output in all_outputs if output.property == "zt"),
        "11_zt_not_dimensional_z": "zt" in property_names and "z" not in TE_PROPERTIES,
        "12_carrier_concentration_not_dopant_concentration": "carrier_concentration" in property_names and "dopant_concentration" not in TE_PROPERTIES,
        "13_mobility_not_conductivity": TE_PROPERTIES["carrier_mobility"].unit_family != TE_PROPERTIES["electrical_conductivity"].unit_family,
        "14_temperature_not_temperature_gradient": all("temperature_gradient" not in output.conditions for output in all_outputs),
        "15_temperature_association_preserved": bool(temperatures) and all(isinstance(value, float) for value in temperatures),
        "16_sample_identity_preserved": all(len(record.material_ids) == 1 for record in all_records),
        "17_composition_preserved": gold_report["material_correct"] and all(material.composition for material in compute_archive.materials),
        "18_dopant_level_preserved": gold_a_archive.materials[0].composition.get("Na") == 0.03 and mixed_archive.materials[0].dopants[0].get("nominal_x") == 0.02,
        "19_process_preserved": gold_report["process_correct"] and len(gold_a_archive.processes[0].parameters) == 10,
        "20_orientation_preserved": all(output.conditions.get("measurement_orientation") for output in all_outputs),
        "21_orientations_not_averaged": reports["TE-ANISO-D"]["orientation_not_averaged"] and {output.conditions["measurement_orientation"] for output in aniso_archive.experiments[0].outputs} == {"c-axis", "ab-plane"},
        "22_missing_temperatures_not_interpolated": reports["TE-GOLD-A"]["outputs"] == 102 and reports["TE-SERIES-B"]["outputs"] == 198 and reports["TE-DERIVED-C"]["outputs"] == 90,
        "23_reported_measurement_not_reported_derived": {output.conditions.get("scientific_type") for output in experimental_outputs}.issuperset({"reported_measurement", "reported_derived_metric"}),
        "24_source_derived_not_synthex_derived": reports["TE-DERIVED-C"]["no_silent_derivation"],
        "25_measured_not_computational": all(output.conditions.get("scientific_type") != "calculated" for output in experimental_outputs) and all(output.conditions.get("scientific_type") == "calculated" for output in calculated_outputs),
        "26_calculated_seebeck_not_measured_seebeck": any(output.property == "seebeck_coefficient" for output in calculated_outputs) and all(output.conditions.get("scientific_type") == "calculated" for output in calculated_outputs if output.property == "seebeck_coefficient"),
        "27_calculated_zt_not_measured_zt": any(output.property == "zt" for output in calculated_outputs) and all(output.conditions.get("scientific_type") == "calculated" for output in calculated_outputs if output.property == "zt"),
        "28_calculated_kappa_not_measured_kappa": any("thermal_conductivity" in output.property for output in calculated_outputs) and all(output.conditions.get("scientific_type") == "calculated" for output in calculated_outputs if "thermal_conductivity" in output.property),
        "29_review_values_remain_non_focal": review_report["passed"] and review_report["focal_records_zero"],
        "30_negative_control_zero_te_contamination": negative_report["passed"] and negative_report["te_records_zero"],
        "31_caption_only_evidence_cannot_admit": caption_rejected,
        "32_na_cannot_become_numeric": na_rejected,
        "33_unit_prefixes_preserved": all(report["passed"] for report in reports.values()) and {output.unit for output in all_outputs}.issuperset({"uV/K", "S/cm", "kS/m"}),
        "34_uv_per_k_not_mv_per_k": all(output.unit == "uV/K" for output in all_outputs if output.property == "seebeck_coefficient"),
        "35_s_per_m_not_s_per_cm": any(output.unit == "S/cm" for output in experimental_outputs if output.property == "electrical_conductivity") and any(output.unit == "kS/m" for output in calculated_outputs if output.property == "electrical_conductivity"),
        "36_w_per_mk_not_power_factor_units": TE_PROPERTIES["total_thermal_conductivity"].unit_family != TE_PROPERTIES["power_factor"].unit_family,
        "37_series_identities_preserved": series_report["scientific_safety"]["sample_association_preserved"] and series_report["scientific_safety"]["three_distinct_samples"],
        "38_same_temperature_across_samples_not_deduplicated": series_report["outputs"] == 198 and series_report["analytics_rows"] == 198,
        "39_analytics_retain_modality": len(analytics) == len(all_outputs) and {row.modality for row in analytics} == {"experimental", "computational"} and mixed_report["modality_split_preserved"],
        "40_archive_domain_scoping_correct": all(archive.domain_payloads[0].domain == "thermoelectrics" for archive in archives.values()) and all(row.domain == "thermoelectrics" for row in analytics),
    }
    evidence_violations = sum(
        not output.evidence or not output.evidence[0].verbatim_match or not output.evidence[0].locator
        or output.raw_value not in (output.evidence[0].text_snippet or "")
        for output in all_outputs
    )
    cross_record_leakage = sum(len(record.material_ids) != 1 for record in all_records)
    analytics_contamination = len(analytics) - len(all_outputs)
    ownership_contamination = sum(
        bool(_quarantine(archive)) for case_id, archive in archives.items() if case_id != "TE-REVIEW-F"
    )
    source_locks = {
        name: _read(name) for name in (
            "source_lock.json", "source_lock_series_b.json", "source_lock_derived_c.json",
            "source_lock_aniso_d.json", "source_lock_compute_e.json", "source_lock_review_f.json",
            "source_lock_neg_g.json", "source_lock_mixed_h.json",
        )
    }
    return {
        "schema": "synthex.thermoelectrics.closure.v1",
        "case_count": len(reports),
        "cases": reports,
        "source_locks": source_locks,
        "totals": {
            "canonical_outputs": len(all_outputs), "experimental_outputs": len(experimental_outputs),
            "computational_outputs": len(calculated_outputs), "analytics_rows": len(analytics),
            "experiments": sum(len(archive.experiments) for archive in canonical_archives),
            "calculations": sum(len(archive.calculations) for archive in canonical_archives),
            "review_noncanonical_values": len(cited_rows),
        },
        "invariants": invariants,
        "invariant_summary": {"passed": sum(invariants.values()), "total": len(invariants), "all_passed": all(invariants.values())},
        "contamination": {
            "ownership": ownership_contamination, "evidence_violations": evidence_violations,
            "cross_record_leakage": cross_record_leakage, "analytics": analytics_contamination,
        },
        "passed": all(report["passed"] for report in reports.values()) and all(invariants.values())
        and not any((ownership_contamination, evidence_violations, cross_record_leakage, analytics_contamination)),
    }
