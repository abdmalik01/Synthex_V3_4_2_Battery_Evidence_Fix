from __future__ import annotations

import json

import pytest

from benchmark.membranes_v1.closure_audit import run_closure_audit
from benchmark.membranes_v1.recover_closure_cases import recover_closure_cases
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.membranes_review_guard import (
    is_explicit_pure_membranes_review,
)
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


@pytest.fixture(scope="module")
def closure():
    return recover_closure_cases()


def test_compute_e_is_calculation_only_with_all_table_2_values(closure):
    archives, _ = closure
    archive = archives["MEM-COMPUTE-E"]
    outputs = [output for item in archive.calculations for output in item.outputs]
    assert len(archive.materials) == len(archive.calculations) == 16
    assert len(outputs) == 32 and not archive.experiments and not archive.devices
    assert {item.property for item in outputs} == {
        "calculated_membrane_permeability_coefficient",
        "calculated_apparent_diffusion_coefficient",
    }
    assert all(item.conditions["scientific_type"] == "simulation_result" for item in outputs)
    assert all(item.conditions["membrane_modality"] == "computational_transport" for item in outputs)
    assert {item.conditions["species"] for item in outputs} == {"O2", "CO2"}


def test_compute_e_analytics_retains_computational_record_and_context(closure):
    archives, _ = closure
    rows = project_results_rows(archives["MEM-COMPUTE-E"])
    assert len(rows) == 32
    assert all(row["record_type"] == "calculation" for row in rows)
    conditions = [json.loads(row["conditions_json"]) for row in rows]
    assert all(item["simulation_method"] == "NAMD2 molecular dynamics with CHARMM36" for item in conditions)
    assert all(
        item["temperature"] == 310.0
        and item["pressure"] == 1.0 and item["pressure_unit"] == "atm"
        and item["boundary_conditions"] == "periodic" and item["time_step_fs"] == 2.0
        and item["analysis_duration_ns"] in {175, 250, 400}
        for item in conditions
    )


def test_review_f_requires_dual_signal_and_contains_cited_values(closure):
    archives, controls = closure
    archive = archives["MEM-REVIEW-F"]
    guarded = controls["review_guarded"]
    review = guarded.domain_values["membranes_review"]
    assert {item["kind"] for item in review["detection_evidence"]} == {
        "publisher_article_type", "author_self_description",
    }
    assert not archive.materials and not archive.devices and not archive.experiments and not archive.calculations
    assert len(review["noncanonical_candidates"]) == 3
    assert all(item["ownership"] == "review_summary" for item in review["noncanonical_candidates"])
    assert not project_results_rows(archive)
    assert all(relation.predicate == "reported_by" for relation in archive.relationships)


@pytest.mark.parametrize("text", ["Review", "This review addresses membrane aging."])
def test_review_guard_does_not_activate_on_one_signal(text):
    bundle = SourceBundle(
        source=SourceMetadata(source_id="one-signal", filename="one.pdf", source_checksum="0" * 64),
        pages=[SourcePageContext(
            page=1, native_text=text, text=text, native_parser="pymupdf", parser="pymupdf",
            origin="native_text", sufficient=True,
        )],
    )
    assert not is_explicit_pure_membranes_review(bundle)


def test_negative_g_routes_batteries_repeatably_with_zero_contamination(closure):
    archives, controls = closure
    archive = archives["MEM-NEG-G"]
    assert controls["negative_route_first"].domain == controls["negative_route_second"].domain == "batteries"
    assert not archive.materials and not archive.devices and not archive.processes
    assert not archive.experiments and not archive.calculations and not project_results_rows(archive)
    assert all(relation.predicate == "reported_by" for relation in archive.relationships)


def test_mixed_h_preserves_architecture_process_and_fouling_modalities(closure):
    archives, _ = closure
    archive = archives["MEM-MIXED-H"]
    assert (len(archive.materials), len(archive.devices), len(archive.processes), len(archive.experiments)) == (3, 5, 5, 9)
    assert sum(len(item.outputs) for item in archive.experiments) == 18
    assert {device.name for device in archive.devices} == {"UF-2P", "UF-4P", "UF-2×4P", "MF-12P", "MF-2×12P"}
    stacked = [device for device in archive.devices if device.configuration["stacked"]]
    assert len(stacked) == 2
    assert all([layer["role"] for layer in device.configuration["layer_stack"]] == ["support", "membrane_body", "membrane_body"] for device in stacked)
    assert all(process.family == "suspension_plasma_spray" for process in archive.processes)
    assert {item.experiment_type for item in archive.experiments} == {
        "dead_end_silica_filtration_fouling",
        "visible_light_self_cleaning_cycles",
        "photocatalytic_and_hydraulic_cleaning",
    }


def test_mixed_h_retains_particle_cycle_and_cleaning_conditions(closure):
    archives, _ = closure
    outputs = [output for item in archives["MEM-MIXED-H"].experiments for output in item.outputs]
    assert {item.conditions["foulant"] for item in outputs} == {"SiO2 200 nm", "SiO2 400 nm", "humic acid"}
    assert {item.conditions.get("cycle") for item in outputs if "cycle" in item.conditions} == {1, 2, 3}
    assert {item.value for item in outputs if item.conditions.get("stage") == "post_cycle_3_final"} == {94.0, 92.0}
    assert all(item.evidence[0].verbatim_match is True and item.evidence[0].page for item in outputs)


def test_membranes_closure_passes_all_forty_invariants():
    report = run_closure_audit()
    assert report["passed"] is True
    assert report["passed_invariants"] == 40
    assert report["canonical_output_total"] == 215
    assert report["contamination"] == {
        "ownership": 0, "evidence": 0, "cross_record_leakage": 0,
        "analytics": 0, "graph": 0,
    }
    assert report["live_gate"]["satisfied"] is True
    assert all(status["schema_valid"] and not status["canonical_admission"] for status in report["normalization"].values())
