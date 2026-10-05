from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthex_platform.benchmarks.corrosion import score_corrosion_archive
from synthex_platform.benchmarks.corrosion_live import (
    calculation_expectations_from_gold,
    load_live_case,
    quarantine_expectations_from_gold,
)
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_computational_recovery import recover_corrosion_computational_tables
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_gravimetric_recovery import recover_corrosion_gravimetric_candidates
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.visual.analytics.projection import project_archives


REPO_ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def dft_case():
    case = load_live_case("CORR-DFT-F", REPO_ROOT)
    bundle = build_source_bundle(case.pdf_path, enable_ocr=False, include_figures=False)
    document = CorrosionDocument.model_validate({
        "source": {"title": case.title, "doi": case.doi},
        "paper_types": ["computational_corrosion"],
    })
    verified = verify_corrosion_document_evidence(
        recover_corrosion_computational_tables(document, bundle), bundle
    )
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)
    gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
    return bundle, verified, archive, gold


def test_corr_dft_f_scores_all_reported_calculations_and_cited_controls(dft_case):
    _, _, archive, gold = dft_case
    expected = calculation_expectations_from_gold(gold)
    quarantine = quarantine_expectations_from_gold(gold)
    score = score_corrosion_archive(archive, expected, quarantine)

    assert len(expected) == 24
    assert score.matched_required == score.total_required == 24
    assert score.value_accuracy == 1.0
    assert score.scientific_type_accuracy == 1.0
    assert score.association_accuracy == 1.0
    assert score.source_tracking_coverage == 1.0
    assert score.quarantine_matches == score.quarantine_total == 3
    assert score.overall == 1.0


def test_corr_dft_f_preserves_method_context_and_direct_table_evidence(dft_case):
    _, verified, archive, _ = dft_case
    assert len(verified.calculations) == 6
    dft = next(item for item in verified.calculations if item.calculation_type == "dft")
    md = next(item for item in verified.calculations if item.calculation_type == "molecular_dynamics")

    assert dft.software == "DMol3 in Materials Studio Modeling 4.0"
    assert dft.functional == "PWC"
    assert dft.basis_set == "DNP"
    assert dft.core_treatment == "all-electron relativistic (AER)"
    assert dft.k_point_grid == "2 x 2 x 1"
    assert md.force_field == "COMPASS"
    assert md.ensemble == "NVE"
    assert md.temperature.raw_value == "303 K"
    assert md.time_step.raw_value == "0.1 fs"
    assert md.simulation_time.raw_value == "0.5 ps"
    assert all(
        evidence.verbatim_match is True and evidence.table_id and evidence.locator
        for calculation in verified.calculations
        for output in calculation.outputs
        for evidence in output.evidence
    )
    assert all(
        output.conditions["data_kind"] == "reported_calculation"
        for calculation in archive.calculations
        for output in calculation.outputs
    )


def test_corr_dft_f_never_casts_computational_or_cited_values_as_experiments(dft_case):
    _, verified, archive, _ = dft_case
    assert len(verified.experiments) == 3
    assert all(experiment.ownership == "cited_prior_work" for experiment in verified.experiments)
    assert archive.experiments == []
    assert len(archive.calculations) == 6
    assert sum(len(item.outputs) for item in archive.calculations) == 24
    assert all(
        output.property not in {"inhibition_efficiency", "corrosion_rate"}
        for calculation in archive.calculations
        for output in calculation.outputs
    )


def test_corr_dft_f_does_not_derive_unreported_descriptors(dft_case):
    _, verified, _, _ = dft_case
    properties = {
        output.property for calculation in verified.calculations for output in calculation.outputs
    }
    assert properties == {
        "homo_energy", "lumo_energy", "chemical_potential", "electron_transfer_number",
        "global_hardness", "binding_energy", "interaction_energy", "total_energy",
    }
    assert all(
        output.data_kind == "reported_calculation"
        for calculation in verified.calculations
        for output in calculation.outputs
    )


def test_corr_dft_f_analytics_projects_calculations_as_computational_rows(dft_case):
    _, _, archive, _ = dft_case
    rows = project_archives([archive])
    assert len(rows) == 24
    assert {row.modality for row in rows} == {"computational"}
    assert {row.record_type for row in rows} == {"dft", "molecular_dynamics"}
    assert not any(row.experiment_id for row in rows)
    assert all(row.calculation_id for row in rows)


def test_corr_dft_f_source_surface_survives_broad_canonical_material_name(dft_case):
    bundle, verified, _, gold = dft_case
    provider_like = verified.model_copy(deep=True)
    provider_like.materials[0].canonical_name = "iron"
    archive = assemble_corrosion_archive(provider_like, source_bundle=bundle)
    score = score_corrosion_archive(archive, calculation_expectations_from_gold(gold))
    assert score.matched_required == score.total_required == 24
    assert any(material.name == "iron surface Fe(110)" for material in archive.materials)
    assert any(material.structure.get("canonical_name") == "iron" for material in archive.materials)


def test_corr_dft_f_swapped_adsorbate_associations_fail_gold(dft_case):
    bundle, verified, _, gold = dft_case
    swapped = verified.model_copy(deep=True)
    ib = next(item for item in swapped.calculations if item.calculation_id == "recovered_dft_ib")
    mb = next(item for item in swapped.calculations if item.calculation_id == "recovered_dft_mb")
    ib.adsorbate_or_inhibitor, mb.adsorbate_or_inhibitor = (
        mb.adsorbate_or_inhibitor, ib.adsorbate_or_inhibitor,
    )
    archive = assemble_corrosion_archive(swapped, source_bundle=bundle)
    score = score_corrosion_archive(archive, calculation_expectations_from_gold(gold))
    assert score.value_matches == 24
    assert score.association_matches < 24
    assert score.matched_required < 24


@pytest.fixture(scope="module")
def mixed_weight_case():
    case = load_live_case("CORR-WEIGHT-E", REPO_ROOT)
    bundle = build_source_bundle(case.pdf_path, enable_ocr=False, include_figures=False)
    document = CorrosionDocument.model_validate({
        "source": {"title": case.title, "doi": case.doi},
        "paper_types": ["inhibitor_study", "immersion_weight_loss", "computational_corrosion"],
        "materials": [{
            "local_id": "mild_steel",
            "reported_name": "mild steel",
            "material_class": "alloy",
            "role": "corroding_material",
            "ownership": "focal_work",
            "evidence": [{"page": 2, "text_snippet": "mild steel", "source_type": "text"}],
        }],
    })
    recovered = recover_corrosion_gravimetric_candidates(document, bundle)
    recovered = recover_corrosion_computational_tables(recovered, bundle)
    verified = verify_corrosion_document_evidence(recovered, bundle)
    return verified, assemble_corrosion_archive(verified, source_bundle=bundle)


def test_mixed_method_paper_keeps_experiments_and_calculations_separate(mixed_weight_case):
    _, archive = mixed_weight_case
    experimental_properties = {
        output.property for experiment in archive.experiments for output in experiment.outputs
    }
    calculation_properties = {
        output.property for calculation in archive.calculations for output in calculation.outputs
    }
    assert {"corrosion_rate", "inhibition_efficiency"} <= experimental_properties
    assert {"homo_energy", "lumo_energy"} <= calculation_properties
    assert experimental_properties.isdisjoint(calculation_properties)
    assert len(archive.calculations) == 1


def test_mixed_method_records_share_supported_entities_without_cross_type_leakage(mixed_weight_case):
    _, archive = mixed_weight_case
    material_ids = {item.material_id for item in archive.materials}
    assert material_ids
    assert all(set(item.material_ids) <= material_ids for item in archive.experiments)
    assert all(set(item.material_ids) <= material_ids for item in archive.calculations)
    predicates = {item.predicate for item in archive.relationships}
    assert {"tested_in", "calculated_for", "calculated_with"} <= predicates
    assert not any(
        output.property in {"homo_energy", "lumo_energy", "energy_gap"}
        for experiment in archive.experiments
        for output in experiment.outputs
    )
