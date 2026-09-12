from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthex_platform.extraction.catalysis_models import (
    CatalysisCalculation, CatalysisDocument, CatalysisEvidence, CatalysisQuantity,
    CatalystMaterial, ElectrochemicalPotential, ElectrocatalysisExperiment,
    ElectrocatalyticMetric, HeterogeneousCatalysisExperiment, HeterogeneousMetric,
    NormalizationBasis, ReactionDefinition, with_stage1_warnings,
)


def _reaction(kind="her"):
    return ReactionDefinition(reported_reaction=kind.upper(), reaction_class=kind)


def test_strict_unknown_fields_are_rejected_and_states_remain_linked_not_merged():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CatalystMaterial(local_id="cat-1", invented_field="no")

    fresh = CatalystMaterial(local_id="cat-1", reported_name="NiFeOx", state="as_synthesized")
    spent = CatalystMaterial(
        local_id="cat-1-spent", reported_name="NiFeOx after OER", state="spent",
        state_parent_ref="cat-1", variant_of="cat-1",
    )
    assert fresh.local_id != spent.local_id
    assert spent.state_parent_ref == fresh.local_id


def test_heterogeneous_conditions_and_product_requirements():
    metric = HeterogeneousMetric(
        property="conversion", raw_value="82%", value=82, unit="%", reactant="CO",
        evidence=[CatalysisEvidence(page=3, text_snippet="CO conversion was 82%")],
    )
    experiment = HeterogeneousCatalysisExperiment(
        experiment_id="ht-1", catalyst_ref="cat-1",
        reaction=ReactionDefinition(reported_reaction="CO oxidation", reaction_class="co_oxidation"),
        reactor_type="fixed-bed", catalyst_mass=CatalysisQuantity(raw_value="100 mg", value=100, unit="mg"),
        feed_composition=[], flow_rate=CatalysisQuantity(raw_value="100 mL/min", value=100, unit="mL/min"),
        whsv=CatalysisQuantity(raw_value="60000 mL g-1 h-1", value=60000, unit="mL/g/h"),
        pressure=CatalysisQuantity(raw_value="1 bar", value=1, unit="bar"), carrier_gas="N2", metrics=[metric],
    )
    assert experiment.metrics[0].reactant == "CO"
    with pytest.raises(ValidationError, match="selectivity must identify its product"):
        HeterogeneousMetric(property="selectivity", raw_value="90%", value=90, unit="%")
    with pytest.raises(ValidationError, match="Catalyst mass cannot be negative"):
        HeterogeneousCatalysisExperiment(experiment_id="bad", reaction=_reaction("unknown"), catalyst_mass=CatalysisQuantity(value=-1, unit="mg"))


def test_product_specific_electrocatalysis_and_partial_current_density():
    potential = ElectrochemicalPotential(
        raw_potential=CatalysisQuantity(raw_value="-0.70 V", value=-0.70, unit="V"),
        reported_reference="Ag/AgCl", filling_solution="3 M KCl", pH=7.0,
    )
    fe = ElectrocatalyticMetric(
        property="faradaic_efficiency", raw_value="82%", value=82, unit="%", product="CO",
        potential=potential, duration=CatalysisQuantity(raw_value="1 h", value=1, unit="h"), analytical_method="GC",
    )
    partial = ElectrocatalyticMetric(
        property="partial_current_density", raw_value="12 mA cm-2", value=12, unit="mA/cm2", product="CO",
        potential=potential, normalization_basis=NormalizationBasis(kind="geometric_area", reported_basis="geometric electrode area", comparison_status="comparable"),
    )
    experiment = ElectrocatalysisExperiment(
        experiment_id="ec-1", catalyst_ref="cat-1", reaction=_reaction("co2rr"), working_electrode="glassy carbon",
        catalyst_loading=CatalysisQuantity(raw_value="0.2 mg cm-2", value=0.2, unit="mg/cm2"),
        electrolyte="KHCO3", electrolyte_concentration=CatalysisQuantity(raw_value="0.5 M", value=0.5, unit="M"),
        pH=7.2, reference_electrode="Ag/AgCl", metrics=[fe, partial],
    )
    assert experiment.metrics[0].product == "CO"
    assert experiment.metrics[1].normalization_basis.kind == "geometric_area"
    with pytest.raises(ValidationError, match="must identify its product"):
        ElectrocatalyticMetric(property="partial_current_density", raw_value="1", value=1, unit="mA/cm2")


def test_potential_reference_is_preserved_without_conversion_and_basis_is_typed():
    raw = ElectrochemicalPotential(
        raw_potential=CatalysisQuantity(raw_value="0.31 V vs SCE", value=0.31, unit="V"),
        reported_reference="SCE", reported_reference_text="saturated calomel electrode",
        filling_solution="saturated KCl", pH=13.8, conversion_status="not_attempted",
    )
    assert raw.converted_potential is None and raw.reported_reference == "SCE"
    with pytest.raises(ValidationError, match="Converted potentials require"):
        ElectrochemicalPotential(
            raw_potential=CatalysisQuantity(value=0.31, unit="V"), reported_reference="SCE",
            converted_potential=CatalysisQuantity(value=1.2, unit="V"), converted_reference="RHE",
        )
    with pytest.raises(ValidationError, match="unknown normalization basis"):
        NormalizationBasis(kind="unknown", comparison_status="comparable")


def test_computational_records_are_explicit_and_stage1_warnings_are_non_mutating():
    calculation = CatalysisCalculation(
        calculation_id="dft-1", material_refs=["cat-1"], calculation_type="dft", code="VASP",
        functional="PBE", dispersion_correction="D3", plane_wave_cutoff_or_basis="450 eV",
        k_points="3x3x1", slab_or_facet="Ni(111)", layers=4,
        outputs=[{"property": "adsorption_free_energy", "raw_value": "-0.24 eV", "value": -0.24, "unit": "eV", "adsorbate_or_intermediate": "H*"}],
    )
    assert calculation.outputs[0].property == "adsorption_free_energy"

    document = CatalysisDocument(electrocatalysis_experiments=[ElectrocatalysisExperiment(
        experiment_id="warn-1", reaction=_reaction("oer"), pH=15.0,
        metrics=[ElectrocatalyticMetric(
            property="faradaic_efficiency", raw_value="101%", value=101, unit="%", product="O2",
            potential=ElectrochemicalPotential(raw_potential=CatalysisQuantity(value=1.6, unit="V"), reported_reference="unknown"),
            normalization_basis=NormalizationBasis(kind="unknown"),
        )],
    )])
    warned = with_stage1_warnings(document)
    assert document.semantic_warnings == []
    assert "warn-1: pH_outside_0_to_14" in warned.semantic_warnings
    assert "warn-1.faradaic_efficiency: percentage_greater_than_100" in warned.semantic_warnings
    assert "warn-1.faradaic_efficiency: normalization_basis_unknown" in warned.semantic_warnings
    assert "warn-1.faradaic_efficiency: potential_reference_unknown" in warned.semantic_warnings
