"""Frozen-gold scorers for PV-COMPUTE-E through PV-MIXED-H."""

from __future__ import annotations

import re

from synthex_platform.visual.analytics.projection import project_archives


def _quarantine_count(archive) -> int:
    return len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])


def score_compute_e(archive, recovered: list[dict], gold: dict) -> dict:
    by_variant = {item.model["simulation_variant"]: item for item in archive.calculations}
    output_names = {
        "simulated_open_circuit_voltage",
        "predicted_short_circuit_current_density",
        "simulated_fill_factor",
        "simulated_power_conversion_efficiency",
    }
    parameter_names = {
        "absorber_acceptor_density_cm3",
        "absorber_defect_density_cm3",
        "czts_thickness_nm",
        "tio2_bandgap_ev",
        "tio2_donor_density_cm3",
    }
    row_matches = []
    for expected in gold["rows"]:
        calculation = by_variant.get(expected["variant"])
        outputs = {item.property: item for item in calculation.outputs} if calculation else {}
        parameters = {item.property: item for item in calculation.parameters} if calculation else {}
        row_matches.append(bool(
            calculation
            and all(outputs[name].value == expected[name] for name in output_names)
            and all(parameters[name].value == expected[name] for name in parameter_names)
            and calculation.code == gold["method"]["software"]
            and calculation.method == gold["method"]["model"]
            and all(item.conditions.get("scientific_type") == "simulation_result" for item in outputs.values())
            and all(item.evidence and item.evidence[0].page == 8 and item.evidence[0].table_id for item in outputs.values())
        ))
    analytics = project_archives([archive])
    checks = {
        "all_five_simulation_rows_match": recovered == gold["rows"] and all(row_matches),
        "calculation_records_only": len(archive.calculations) == 5 and not archive.experiments,
        "zero_experimental_records": not archive.experiments and not archive.devices,
        "simulated_properties_use_distinct_identities": all(
            {item.property for item in calculation.outputs} == output_names
            for calculation in archive.calculations
        ),
        "method_context_retained": all(
            calculation.model.get("illumination_spectrum") == "AM1.5G"
            and calculation.model.get("temperature_k") == 300
            and calculation.model.get("architecture") == gold["method"]["architecture"]
            for calculation in archive.calculations
        ),
        "material_and_architecture_retained": len(archive.materials) == 1 and all(item.material_ids for item in archive.calculations),
        "value_specific_evidence_retained": all(
            output.evidence and output.raw_value in (output.evidence[0].text_snippet or "")
            for calculation in archive.calculations for output in calculation.outputs
        ),
        "analytics_rows_marked_computational": len(analytics) == 20 and all(
            row.modality == "computational" and row.calculation_id and row.material_id for row in analytics
        ),
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "materials": len(archive.materials), "devices": len(archive.devices),
        "experiments": len(archive.experiments), "calculations": len(archive.calculations),
        "outputs": sum(len(item.outputs) for item in archive.calculations),
        "analytics_rows": len(analytics), "ownership_violations": 0,
        "evidence_violations": 0 if checks["value_specific_evidence_retained"] else 1,
        "cross_record_leakage": len(archive.experiments),
        "analytics_contamination_count": sum(row.modality != "computational" for row in analytics),
        "quarantine_count": _quarantine_count(archive),
    }


def score_review_f(archive, guarded, route, gold: dict) -> dict:
    review = archive.domain_payloads[0].values["photovoltaics_review"]
    candidates = review["noncanonical_candidates"]
    experiment_candidates = [item for item in candidates if item["kind"] == "experiment"]
    preserved_outputs = experiment_candidates[0]["raw_object"]["outputs"] if experiment_candidates else []
    expected = gold["reviewed_noncanonical_example"]
    expected_values = {
        "power_conversion_efficiency": expected["power_conversion_efficiency"],
        "open_circuit_voltage": expected["open_circuit_voltage"],
        "short_circuit_current_density": expected["short_circuit_current_density"],
        "fill_factor": float(expected["fill_factor_raw"]),
    }
    actual_values = {item["property"]: item["value"] for item in preserved_outputs}
    evidence_retained = bool(preserved_outputs and all(item.get("evidence") for item in preserved_outputs))
    analytics = project_archives([archive])
    graph = [item for item in archive.relationships if item.predicate != "reported_by"]
    checks = {
        "photovoltaics_route": route.domain == "photovoltaics",
        "review_paper_type": "review" in route.paper_types,
        "explicit_two_signal_review_detection": review["classification"] == "explicit_review" and {
            item["kind"] for item in review["detection_evidence"]
        } == {"publisher_article_type", "author_self_description"},
        "zero_focal_experiments": not archive.experiments,
        "zero_focal_calculations": not archive.calculations,
        "zero_canonical_performance_outputs": not archive.experiments and not archive.calculations,
        "cited_values_preserved_noncanonical": actual_values == expected_values,
        "evidence_retained": evidence_retained,
        "zero_graph_contamination": not graph,
        "zero_analytics_contamination": not analytics,
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    ownership_violations = sum(
        item["ownership"] not in {"cited_prior_work", "review_summary", "comparison_table"}
        for item in candidates
    )
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "route": route.domain, "paper_types": route.paper_types,
        "review_classification": review["classification"],
        "noncanonical_candidate_count": len(candidates),
        "canonical_devices": len(archive.devices), "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations), "canonical_outputs": 0,
        "ownership_violations": ownership_violations,
        "evidence_violations": 0 if evidence_retained else 1,
        "cross_record_leakage": 0,
        "analytics_contamination_count": len(analytics),
        "graph_contamination_count": len(graph),
    }


def score_negative_g(archive, first, second, text: str, gold: dict) -> dict:
    lowered = text.casefold()
    overlap = [term for term in gold["misleading_vocabulary"] if term.casefold() in lowered]
    analytics = project_archives([archive])
    graph = [item for item in archive.relationships if item.predicate != "reported_by"]
    metrics = [
        output for item in [*archive.experiments, *archive.calculations] for output in item.outputs
    ]
    repeat_same = (
        first.domain == second.domain and first.scores == second.scores
        and first.matched_terms == second.matched_terms and first.paper_types == second.paper_types
    )
    checks = {
        "source_is_primary_photocatalysis_study": gold["source"]["true_domain"] == "catalysis" and gold["source"]["article_type"] == "Article",
        "routes_to_catalysis": first.domain == gold["expected_route"],
        "repeat_route_is_identical": repeat_same,
        "misleading_pv_vocabulary_present": set(overlap) == set(gold["misleading_vocabulary"]),
        "zero_pv_devices": not archive.devices,
        "zero_pv_experiments": not archive.experiments,
        "zero_pv_calculations": not archive.calculations,
        "zero_pv_metrics": not metrics,
        "zero_graph_contamination": not graph,
        "zero_analytics_contamination": not analytics,
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "route": first.domain, "route_confidence": first.confidence,
        "scores": first.scores, "paper_types": first.paper_types,
        "misleading_vocabulary_detected": overlap,
        "matched_pv_terms": first.matched_terms.get("photovoltaics", []),
        "focal_pv_signals": first.focal_signals.get("photovoltaics", []),
        "canonical_devices": len(archive.devices), "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations), "canonical_metrics": len(metrics),
        "ownership_violations": 0, "evidence_violations": 0, "cross_record_leakage": 0,
        "analytics_contamination_count": len(analytics), "graph_contamination_count": len(graph),
    }


def score_mixed_h(archive, gold: dict) -> dict:
    variants = {item.configuration.get("variant"): item for item in archive.devices}
    device_variants = {item.device_id: item.configuration.get("variant") for item in archive.devices}
    actual = {}
    for experiment in archive.experiments:
        variant = device_variants.get(experiment.device_id)
        for output in experiment.outputs:
            modality = output.conditions.get("measurement_modality")
            actual[(variant, modality, output.property)] = output
    measurement_matches = []
    for expected in gold["measurements"]:
        output = actual.get((expected["variant"], expected["modality"], expected["property"]))
        measurement_matches.append(bool(
            output and output.value == expected["value"] and output.unit == expected["unit"]
            and output.qualifier == expected.get("qualifier", "exact")
            and ("aging_time_h" not in expected or output.conditions.get("aging_time") == expected["aging_time_h"])
        ))
    process_concentrations = {
        next(device_variants.get(value) for value in item.outputs if value in device_variants): item.parameters[0].value
        for item in archive.processes
    }
    analytics = project_archives([archive])
    modalities = {row.conditions.get("measurement_modality") for row in analytics}
    evidence_ok = all(
        output.evidence and output.evidence[0].verbatim_match is True
        and output.raw_value in (output.evidence[0].text_snippet or "")
        for experiment in archive.experiments for output in experiment.outputs
    )
    checks = {
        "two_device_variants_distinct": set(variants) == {"pristine", "o_cb"} and len({item.device_id for item in variants.values()}) == 2,
        "ordered_stack_retained": all(
            [layer["role"] for layer in item.configuration["layer_stack"]] == gold["layer_roles"]
            and [layer["sequence_index"] for layer in item.configuration["layer_stack"]] == list(range(6))
            for item in archive.devices
        ),
        "process_variant_retained": process_concentrations == {"pristine": 0.0, "o_cb": 1.0},
        "performance_values_match": all(measurement_matches[:4]),
        "spectral_summaries_match": all(measurement_matches[4:6]) and not any(
            output.property == "external_quantum_efficiency"
            for experiment in archive.experiments for output in experiment.outputs
        ),
        "stability_values_match": all(measurement_matches[6:]),
        "all_modalities_device_linked": len(analytics) == len(gold["measurements"]) and all(row.device_id for row in analytics),
        "modalities_remain_separate": modalities == {"performance", "spectral_summary", "stabilized_output", "thermal_stability"},
        "evidence_and_ownership_retained": evidence_ok and _quarantine_count(archive) == 0,
        "analytics_context_retained": all(
            row.conditions.get("device_variant") in {"pristine", "o_cb"}
            and row.conditions.get("device_architecture") == gold["architecture"]
            for row in analytics
        ),
    }
    assertions = [{"id": name, "passed": bool(checks[name])} for name in gold["assertions"]]
    return {
        "case_id": gold["case_id"], "passed": sum(item["passed"] for item in assertions),
        "total": len(assertions), "assertions": assertions,
        "materials": len(archive.materials), "devices": len(archive.devices),
        "processes": len(archive.processes), "experiments": len(archive.experiments),
        "calculations": len(archive.calculations),
        "outputs": sum(len(item.outputs) for item in archive.experiments),
        "analytics_rows": len(analytics), "modalities": sorted(modalities),
        "ownership_violations": 0, "evidence_violations": 0 if evidence_ok else 1,
        "cross_record_leakage": 0 if checks["modalities_remain_separate"] else 1,
        "analytics_contamination_count": 0 if checks["analytics_context_retained"] else 1,
        "quarantine_count": _quarantine_count(archive),
    }
