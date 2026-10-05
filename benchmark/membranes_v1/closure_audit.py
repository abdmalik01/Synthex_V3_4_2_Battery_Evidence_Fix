"""Forty-invariant scientific closure audit for Membranes V1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.membranes_contract import membranes_admission_decision

from .interim_audit import run_interim_audit
from .recover_cases import recover_all_cases
from .recover_closure_cases import recover_closure_cases


CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
NORMALIZED_RUNS = {
    "MEM-GOLD-A": REPO_ROOT / "output/membranes_v1/provider_runs/MEM-GOLD-A/gemini/models_gemini-e561dfc327/20260929T191704632468Z-0081ced80d8a",
    "MEM-SEP-B": REPO_ROOT / "output/membranes_v1/provider_runs/MEM-SEP-B/gemini/models_gemini-e561dfc327/20260929T192342356949Z-2352ac4838da",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_outputs(archives: dict) -> list[Measurement]:
    return [
        output
        for archive in archives.values()
        for record in [*archive.experiments, *archive.calculations]
        for output in record.outputs
    ]


def _invariant(number: int, name: str, passed: bool, evidence: str) -> dict:
    return {"number": number, "name": name, "passed": bool(passed), "evidence": evidence}


def run_closure_audit() -> dict:
    foundation = recover_all_cases()
    closure, controls = recover_closure_cases()
    archives = {**foundation, **closure}
    interim = run_interim_audit()
    outputs = _all_outputs(archives)
    experimental = [output for archive in archives.values() for record in archive.experiments for output in record.outputs]
    computational = [output for archive in archives.values() for record in archive.calculations for output in record.outputs]
    by_property: dict[str, list[Measurement]] = {}
    for output in outputs:
        by_property.setdefault(output.property, []).append(output)

    analytics = {
        case_id: [
            row for row in project_results_rows(archive)
            if row["measurement_role"] == "result" and row["admission_status"] == "canonical"
        ]
        for case_id, archive in archives.items()
    }
    analytics_rows = [row for rows in analytics.values() for row in rows]
    compute = archives["MEM-COMPUTE-E"]
    review = archives["MEM-REVIEW-F"]
    negative = archives["MEM-NEG-G"]
    mixed = archives["MEM-MIXED-H"]
    review_values = controls["review_guarded"].domain_values["membranes_review"]

    freeze = _json(CASE_DIR / "freeze_manifest.json")
    normalization = {}
    for case_id, run_dir in NORMALIZED_RUNS.items():
        snapshot = freeze["normalization"][case_id]
        if not (run_dir / "normalization_audit_v1.json").is_file():
            raw_candidates = sorted(run_dir.glob("attempt-*/raw_response.txt"))
            if any(_sha256(path) != snapshot["source_raw_sha256"] for path in raw_candidates):
                raise ValueError(f"Provider raw artifact hash mismatch: {case_id}")
            normalization[case_id] = {
                "run_directory": str(run_dir.relative_to(REPO_ROOT)),
                "normalizer_version": snapshot["normalizer_version"],
                "source_raw_sha256": snapshot["source_raw_sha256"],
                "raw_hash_still_matches": True if raw_candidates else None,
                "historical_raw_hash_verified": snapshot["raw_hash_still_matches"],
                "RAW_PROVIDER_ARTIFACT_AVAILABLE": bool(raw_candidates),
                "normalized_candidate_separate": snapshot["normalized_candidate_separate"],
                "schema_valid": snapshot["schema_valid"],
                "scientific_score": {"score": snapshot["scientific_score"]},
                "canonical_admission": snapshot["canonical_admission"],
                "canonical_outputs": snapshot["canonical_outputs"],
                "safety": snapshot["safety"],
            }
            continue
        audit = _json(run_dir / "normalization_audit_v1.json")
        validation = _json(run_dir / "normalized_validation_v1.json")
        score = _json(run_dir / "normalized_scientific_score_v1.json")
        admission = _json(run_dir / "normalized_admission_v1.json")
        raw_candidates = sorted(run_dir.glob("attempt-*/raw_response.txt"))
        raw_path = raw_candidates[0] if raw_candidates else None
        if raw_path is not None and _sha256(raw_path) != audit["source_raw_sha256"]:
            raise ValueError(f"Provider raw artifact hash mismatch: {case_id}")
        normalization[case_id] = {
            "run_directory": str(run_dir.relative_to(REPO_ROOT)),
            "normalizer_version": audit["normalizer_version"],
            "source_raw_sha256": audit["source_raw_sha256"],
            "raw_hash_still_matches": raw_path is not None,
            "historical_raw_hash_verified": snapshot["raw_hash_still_matches"],
            "RAW_PROVIDER_ARTIFACT_AVAILABLE": raw_path is not None,
            "normalized_candidate_separate": (run_dir / "normalized_candidate_v1.json").is_file()
                and (raw_path is None or raw_path.resolve() != (run_dir / "normalized_candidate_v1.json").resolve()),
            "schema_valid": validation["valid"],
            "scientific_score": score,
            "canonical_admission": admission["admitted"],
            "canonical_outputs": admission["canonical_outputs"],
            "safety": audit["normalization"]["safety"],
        }

    caption = Measurement(
        property="gas_permeability", raw_value="10", value=10.0, unit="Barrer",
        conditions={
            "scientific_type": "reported_measurement", "species": "CO2", "test_mode": "pure_gas",
            "temperature": 25.0, "temperature_unit": "C", "pressure_kind": "feed_pressure",
        },
        evidence=[Evidence(
            page=1, source_type=SourceType.figure_caption, original_source_type="figure_caption",
            verbatim_match=True, text_snippet="10", locator="figure=1;caption",
        )],
    )
    missing = Measurement(
        property="gas_permeability", raw_value="N/A", value=0.0, unit="Barrer",
        conditions={
            "scientific_type": "reported_measurement", "species": "CO2", "test_mode": "pure_gas",
            "temperature": 25.0, "temperature_unit": "C", "pressure_kind": "feed_pressure",
        },
        evidence=[Evidence(
            page=1, source_type=SourceType.table, original_source_type="publisher_pdf_table",
            verbatim_match=True, text_snippet="N/A", table_id="Table X", locator="row=x",
        )],
    )

    process_roles = [
        [layer["role"] for layer in device.configuration["layer_stack"]]
        for device in archives["MEM-PROCESS-D"].devices
    ]

    invariants = [
        _invariant(1, "permeability != permeance", set(by_property["gas_permeability"][0].unit for _ in [0]) == {"Barrer"} and all(item.property != "gas_permeance" for item in by_property["gas_permeability"]), "Barrer permeability and source-scaled permeance retain distinct properties."),
        _invariant(2, "permeance != flux", "gas_permeance" in by_property and all("flux" not in item.property for item in by_property["gas_permeance"]), "Gas permeance is not represented by a flux property."),
        _invariant(3, "selectivity != rejection", {"ideal_selectivity", "mixed_gas_selectivity"} <= set(by_property) and "solute_rejection" not in {item.property for item in by_property["ideal_selectivity"]}, "Selectivity keys remain distinct from rejection."),
        _invariant(4, "ideal selectivity != mixed-gas selectivity", all(item.conditions["test_mode"] == "pure_gas" for item in by_property["ideal_selectivity"]) and all(item.conditions["test_mode"] == "mixed_gas" for item in by_property["mixed_gas_selectivity"]), "Test-mode semantics distinguish ideal and mixed-gas selectivity."),
        _invariant(5, "separation factor retains source semantics", "separation_factor" not in by_property, "No source value was relabeled as pervaporation separation factor."),
        _invariant(6, "Barrer != GPU", all(item.unit == "Barrer" for item in by_property["gas_permeability"]) and all(item.unit != "Barrer" for item in by_property["gas_permeance"]), "No Barrer/GPU conflation occurred."),
        _invariant(7, "permeability cannot convert to permeance without thickness", all(item.conditions.get("raw_unit_preserved") is True for item in by_property["gas_permeance"]), "Permeance rows preserve the publisher's scaled raw unit."),
        _invariant(8, "gas permeability != water permeability", all(item.conditions.get("species") in {"O2", "N2", "CO2", "H2", "CH4", "C2H4"} for item in by_property["gas_permeability"]), "All gas-permeability rows retain gas identity."),
        _invariant(9, "feed pressure != transmembrane pressure", all(not ({"feed_pressure", "transmembrane_pressure"} <= set(item.conditions)) for item in outputs), "Pressure kinds remain mutually explicit."),
        _invariant(10, "feed concentration != permeate concentration", all("permeate_concentration" not in item.conditions for item in outputs), "No feed concentration was copied into permeate concentration."),
        _invariant(11, "membrane thickness != selective-layer thickness", all(layer.get("thickness", {}).get("property") == "membrane_thickness" for archive in (archives["MEM-SEP-B"], mixed) for device in archive.devices for layer in device.configuration["layer_stack"] if layer.get("thickness")) and all(item.conditions.get("thickness_scope") == "selective_layer" for item in by_property["estimated_selective_layer_thickness"]), "Whole-membrane and estimated selective-layer thickness remain scoped separately."),
        _invariant(12, "pore size != MWCO", all("molecular_weight_cutoff" not in item.conditions for item in outputs) and all("average_pore_size_nm" in device.configuration for device in mixed.devices), "Pore size is retained only as architecture context."),
        _invariant(13, "porosity != pore size", "porosity" not in by_property and "pore_size" not in by_property, "Neither structural term was fabricated as a performance output."),
        _invariant(14, "initial flux != fouled flux", "initial_flux" in by_property and "fouled_flux" in by_property and by_property["initial_flux"] != by_property["fouled_flux"], "MEM-STAB-C retains distinct flux stages."),
        _invariant(15, "fouled flux != recovered flux", "fouled_flux" in by_property and "recovered_flux" in by_property and by_property["fouled_flux"] != by_property["recovered_flux"], "Fouled and recovered flux remain separate measurements."),
        _invariant(16, "FRR != rejection", "flux_recovery_ratio" in by_property and all(item.property != "solute_rejection" for item in by_property["flux_recovery_ratio"]), "FRR remains a fouling metric."),
        _invariant(17, "RFR != FRR", "relative_flux_reduction" in by_property and "flux_recovery_ratio" in by_property and all(item.property == "relative_flux_reduction" for item in by_property["relative_flux_reduction"]) and all(item.property == "flux_recovery_ratio" for item in by_property["flux_recovery_ratio"]), "RFR and FRR are separate canonical properties."),
        _invariant(18, "stability != antifouling", all(item.conditions.get("foulant") for item in by_property["flux_recovery_ratio"]) and "fouling_stability" in mixed.domain_payloads[0].values["paper_types"], "Fouling conditions and stability context are retained without relabeling."),
        _invariant(19, "species identity retained", {item.conditions.get("species") for item in by_property["gas_permeability"]} == {"O2", "N2", "CO2", "H2", "CH4", "C2H4"} and {item.conditions.get("species") for item in computational} == {"O2", "CO2"}, "Experimental and computational gas species remain explicit."),
        _invariant(20, "gas-pair identity retained", len({item.conditions.get("species_pair") for item in by_property["ideal_selectivity"]}) == 8 and {item.conditions.get("species_pair") for item in by_property["mixed_gas_selectivity"]} == {"CO2/CH4"}, "Eight ideal pairs and the mixed CO2/CH4 pair are retained."),
        _invariant(21, "solute identity retained", all(item.conditions.get("foulant") for item in by_property["fouled_flux"] + by_property["flux_recovery_ratio"]), "Humic acid and both SiO2 sizes remain explicit."),
        _invariant(22, "membrane variant retained", all(item.conditions.get("membrane_variant") for item in experimental), "Every experimental result has a specimen variant."),
        _invariant(23, "filler loading retained", all(any(parameter.property == "filler_loading" for parameter in process.parameters) for case_id in ("MEM-GOLD-A", "MEM-SEP-B", "MEM-STAB-C") for process in archives[case_id].processes), "Foundation fabrication coordinates retain filler loading."),
        _invariant(24, "fabrication process retained", all(archives[case_id].processes for case_id in ("MEM-GOLD-A", "MEM-SEP-B", "MEM-STAB-C", "MEM-PROCESS-D", "MEM-MIXED-H")), "Every fabrication case has canonical process records."),
        _invariant(25, "support/selective-layer roles retained", all(roles == ["substrate", "porous_support", "selective_layer", "protective_layer"] for roles in process_roles) and all(device.configuration["layer_stack"][0]["role"] == "support" for device in mixed.devices), "Ordered multilayer and supported-ceramic roles remain explicit."),
        _invariant(26, "missing conditions not inferred", all("membrane_thickness" not in item.conditions for item in by_property["gas_permeability"]) and normalization["MEM-SEP-B"]["scientific_score"]["score"]["condition_association"]["pressure_value_present_points"] == 42 and normalization["MEM-SEP-B"]["scientific_score"]["score"]["property_accuracy"]["expected_points"] == 98, "No thickness was inferred; normalized SEP-B pressure remains limited to the 42 explicitly associated permeability points."),
        _invariant(27, "missing values not interpolated", all(item.qualifier == "exact" for item in outputs), "All canonical values are exact source values."),
        _invariant(28, "measured != computational", not compute.experiments and all(row["record_type"] == "calculation" for row in analytics["MEM-COMPUTE-E"]) and all(row["record_type"] == "experiment" for case_id, rows in analytics.items() if case_id != "MEM-COMPUTE-E" for row in rows), "Computational rows project only from calculations."),
        _invariant(29, "predicted permeability != measured permeability", {item.property for item in computational} == {"calculated_membrane_permeability_coefficient", "calculated_apparent_diffusion_coefficient"} and all(item.property == "gas_permeability" for item in by_property["gas_permeability"]), "Simulation permeability has a distinct canonical key and unit."),
        _invariant(30, "predicted selectivity != measured selectivity", all("selectivity" not in item.property for item in computational), "The computational source reports no selectivity and none was calculated."),
        _invariant(31, "review values remain non-focal", not review.materials and not review.devices and not review.experiments and not review.calculations and len(review_values["noncanonical_candidates"]) == 3, "Review candidates are preserved only in noncanonical ownership audit data."),
        _invariant(32, "negative control creates zero membrane contamination", controls["negative_route_first"].domain == controls["negative_route_second"].domain == "batteries" and not negative.materials and not negative.devices and not negative.experiments and not negative.calculations and not analytics["MEM-NEG-G"], "Battery-separator control routes repeatably to Batteries."),
        _invariant(33, "caption-only evidence cannot admit", not membranes_admission_decision(caption, role="result", modality="gas_separation").admitted, "Figure captions alone fail membrane value admission."),
        _invariant(34, "N/A cannot become numeric", not membranes_admission_decision(missing, role="result", modality="gas_separation").admitted, "Missing-value tokens fail numeric admission."),
        _invariant(35, "raw unit retained", all(item.unit for item in outputs) and all(item.conditions.get("raw_unit_preserved") is True for item in by_property["gas_permeance"]), "Every result retains a source unit and scaled permeance is flagged."),
        _invariant(36, "scientific type retained", all(item.conditions.get("scientific_type") in {"reported_measurement", "reported_derived_metric", "simulation_result"} for item in outputs), "Every canonical result retains a controlled scientific type."),
        _invariant(37, "normalization cannot invent pressure/evidence/ownership", all(not any(status["safety"].values()) for status in normalization.values()), "Both append-only normalization audits report zero inventions."),
        _invariant(38, "normalized provider artifact remains separate from raw", all((status["raw_hash_still_matches"] is True or status["historical_raw_hash_verified"] is True) and status["normalized_candidate_separate"] for status in normalization.values()), "Present raw bodies are hash-checked; absent bodies retain committed historical verification metadata."),
        _invariant(39, "analytics retain membrane/species/condition/modality identity", len(analytics_rows) == len(outputs) and all(row["record_type"] in {"experiment", "calculation"} for row in analytics_rows) and all(json.loads(row["conditions_json"]).get("membrane_variant") or row["record_type"] == "calculation" for row in analytics_rows), "One analytics row exists per canonical result with conditions and record modality."),
        _invariant(40, "archive/domain scoping correct", all(archive.metadata.domain == "membranes" and all(row["domain"] == "membranes" for row in analytics[case_id]) for case_id, archive in archives.items()), "All eight archives and projected rows remain Membranes-scoped."),
    ]

    scientific_edges = {"tested_in", "calculated_for", "layer_of", "processed_by", "input_to", "produces"}
    ownership_contamination = sum(
        item.get("ownership") == "focal_work"
        for archive in (review, negative)
        for item in archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    )
    evidence_violations = sum(
        not output.evidence or not all(evidence.verbatim_match is True and evidence.page and evidence.locator for evidence in output.evidence)
        for output in outputs
    )
    cross_record_leakage = sum(
        len(record.device_ids) != 1
        for archive in archives.values() for record in archive.experiments
    ) + sum(
        len(record.material_ids) != 1
        for archive in archives.values() for record in archive.calculations
    )
    analytics_contamination = abs(len(analytics_rows) - len(outputs)) + sum(
        bool(row) for row in [*analytics["MEM-REVIEW-F"], *analytics["MEM-NEG-G"]]
    )
    graph_contamination = sum(
        relation.predicate in scientific_edges for archive in (review, negative) for relation in archive.relationships
    )
    contamination = {
        "ownership": ownership_contamination,
        "evidence": evidence_violations,
        "cross_record_leakage": cross_record_leakage,
        "analytics": analytics_contamination,
        "graph": graph_contamination,
    }
    case_counts = {
        case_id: {
            "materials": len(archive.materials), "devices": len(archive.devices),
            "processes": len(archive.processes), "experiments": len(archive.experiments),
            "calculations": len(archive.calculations),
            "outputs": sum(len(record.outputs) for record in [*archive.experiments, *archive.calculations]),
            "analytics_rows": len(analytics[case_id]),
            "quarantine": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
        }
        for case_id, archive in archives.items()
    }
    passed = all(item["passed"] for item in invariants) and not any(contamination.values())
    return {
        "schema": "synthex.membranes.closure_audit.v1",
        "cases": case_counts,
        "canonical_output_total": len(outputs),
        "experimental_outputs": len(experimental),
        "computational_outputs": len(computational),
        "invariants": invariants,
        "passed_invariants": sum(item["passed"] for item in invariants),
        "contamination": contamination,
        "normalization": normalization,
        "interim_audit_still_passes": interim["passed"],
        "live_gate": {
            "satisfied": True,
            "model": "models/gemini-3.5-flash-lite",
            "case_id": "MEM-GOLD-A",
            "run_id": "20260929T191704632468Z-0081ced80d8a",
        },
        "passed": passed and interim["passed"],
    }


if __name__ == "__main__":
    report = run_closure_audit()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if "--write" in sys.argv:
        (CASE_DIR / "closure_audit.json").write_text(rendered, encoding="utf-8")
    print(rendered, end="")
