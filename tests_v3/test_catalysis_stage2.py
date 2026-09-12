from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from synthex_platform.extraction.catalysis_assembler import assemble_catalysis_archive
from synthex_platform.extraction.catalysis_evidence import verify_catalysis_evidence
from synthex_platform.extraction.catalysis_models import (
    CatalysisCalculation,
    CatalysisConditionConflict,
    CatalysisDocument,
    CatalysisEvidence,
    CatalysisQuantity,
    CatalystMaterial,
    ComputationalMetric,
    ElectrochemicalPotential,
    ElectrocatalysisExperiment,
    ElectrocatalyticMetric,
    HeterogeneousCatalysisExperiment,
    HeterogeneousMetric,
    NormalizationBasis,
    ReactionDefinition,
    StabilityTest,
)
from synthex_platform.extraction.catalysis_normalizer import comparability_status, normalization_key
from synthex_platform.extraction.pipeline import SynthexExtractionPipeline
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.visual.models import TableCell, TableRecord, VisualProvenance


TEXT = """--- PAGE 1 ---
Pt/C catalyst was prepared. At 300 °C, CO conversion was 82% over Pt/C.
CO Faradaic efficiency was 92% at -0.70 V vs RHE and its partial current density was 10 mA/cm² geometric.
The retained activity was 90% after 10 h at 300 °C.
DFT gave an H adsorption free energy of -0.24 eV using PBE.
"""


def ev(snippet: str, origin: str = "native_text", **kwargs):
    source_type = "table" if origin == "table_reported" else "figure" if origin.startswith("figure_") else "text"
    return CatalysisEvidence(
        page=1, text_snippet=snippet, source_type=source_type,
        original_source_type=origin, **kwargs,
    )


def catalyst(local_id="cat-1", state="as_synthesized", parent=None, ownership="focal_work"):
    return CatalystMaterial(
        local_id=local_id, reported_name="Pt/C", state=state,
        state_parent_ref=parent, ownership=ownership,
        evidence=[ev("Pt/C catalyst was prepared")],
    )


def reaction(kind="co_oxidation"):
    return ReactionDefinition(
        reported_reaction="CO oxidation" if kind == "co_oxidation" else kind.upper(),
        reaction_class=kind,
        reactants=[{"reported_name": "CO"}] if kind == "co_oxidation" else [],
        products=[{"reported_name": "CO2"}] if kind == "co_oxidation" else [],
    )


def hetero_metric(ownership="focal_work", origin="native_text"):
    return HeterogeneousMetric(
        property="conversion", raw_value="82%", value=82, unit="%", reactant="CO",
        ownership=ownership, evidence=[ev("CO conversion was 82%", origin)],
    )


def hetero_doc(metric=None, *, conflicts=None, catalysts=None):
    return CatalysisDocument(
        source={"title": "Offline catalysis fixture"},
        paper_types=["heterogeneous_catalysis"],
        catalysts=catalysts or [catalyst()],
        heterogeneous_experiments=[HeterogeneousCatalysisExperiment(
            experiment_id="exp-1", catalyst_ref="cat-1", reaction=reaction(),
            temperature=CatalysisQuantity(raw_value="300 °C", value=300, unit="°C"),
            metrics=[metric or hetero_metric()], ownership="focal_work",
            evidence=[ev("At 300 °C, CO conversion was 82% over Pt/C")],
        )],
        condition_conflicts=conflicts or [],
    )


def bundle(*, ocr=False, table=False):
    tables = []
    if table:
        provenance = VisualProvenance(
            origin="table_reported", source_id="src-fixture", page=1,
            object_id="tbl-1", object_type="table", cell_id="cell-1", raw_text="82%",
        )
        cell = TableCell(row=1, column=2, cell_id="cell-1", raw_text="82%", provenance=provenance)
        tables = [TableRecord(
            table_id="tbl-1", source_id="src-fixture", page=1, cells=[cell],
            raw_representation={"grid": [["conversion", "82%"]]}, provenance=provenance,
        )]
    page_text = TEXT.split("--- PAGE 1 ---\n", 1)[1]
    return SourceBundle(
        source=SourceMetadata(source_id="src-fixture", filename="fixture.pdf", source_checksum="abc123"),
        pages=[SourcePageContext(
            page=1, native_text="" if ocr else page_text, text=page_text,
            native_parser="none" if ocr else "pypdf", parser="ocr" if ocr else "pypdf",
            origin="ocr_extracted" if ocr else "native_text", sufficient=True,
        )], tables=tables,
    )


def audit(archive):
    return archive.domain_payloads[0].values["admissibility_audit"]


def test_focal_native_heterogeneous_value_is_admitted_and_referentially_valid():
    archive = assemble_catalysis_archive(hetero_doc(), source_text=TEXT)
    assert archive.experiments[0].outputs[0].property == "conversion"
    assert archive.experiments[0].outputs[0].value == 82
    assert audit(archive)["admitted_quantitative_values"] >= 1
    assert archive.model_validate(archive.model_dump())


def test_review_or_cited_value_is_quarantined_without_experiment_leakage():
    archive = assemble_catalysis_archive(hetero_doc(hetero_metric("cited_prior_work")), source_text=TEXT)
    assert archive.experiments == []
    assert any(item["reason"] == "ownership_cited_prior_work" for item in audit(archive)["quarantine"])


def test_exact_table_cell_verification_and_locator_preservation():
    evidence = ev("82%", "table_reported", table_id="tbl-1", locator="row=1;column=2;cell_id=cell-1")
    metric = HeterogeneousMetric(property="conversion", raw_value="82%", value=82, unit="%", reactant="CO", ownership="focal_work", evidence=[evidence])
    source_bundle = bundle(table=True)
    assert verify_catalysis_evidence(evidence, source_bundle=source_bundle)
    archive = assemble_catalysis_archive(hetero_doc(metric), source_bundle=source_bundle, source_text=source_bundle.page_marked_text())
    canonical = archive.experiments[0].outputs[0].evidence[0]
    assert canonical.original_source_type == "table_reported" and "cell_id=cell-1" in canonical.locator


def test_ocr_origin_is_preserved_and_digitized_values_are_rejected():
    ocr_bundle = bundle(ocr=True)
    metric = hetero_metric(origin="ocr_extracted")
    archive = assemble_catalysis_archive(hetero_doc(metric), source_bundle=ocr_bundle, source_text=ocr_bundle.page_marked_text())
    verified = archive.domain_payloads[0].values["validated_document"]["heterogeneous_experiments"][0]["metrics"][0]["evidence"][0]
    assert verified["original_source_type"] == "ocr_extracted"
    assert verified["evidence_strength"] == "verified_ocr"
    digitized = hetero_metric(origin="figure_digitized")
    digitized.evidence[0].estimated = True
    rejected = assemble_catalysis_archive(hetero_doc(digitized), source_text=TEXT)
    assert rejected.experiments == []
    assert any(item["reason"] == "estimated_digitized" for item in audit(rejected)["quarantine"])


def test_potential_reference_is_raw_and_incomplete_conversion_stays_null():
    potential = ElectrochemicalPotential(
        raw_potential=CatalysisQuantity(raw_value="-0.70 V vs Ag/AgCl", value=-0.70, unit="V"),
        reported_reference="Ag/AgCl", filling_solution=None, conversion_status="incomplete",
    )
    metric = ElectrocatalyticMetric(
        property="faradaic_efficiency", raw_value="92%", value=92, unit="%",
        product="CO", potential=potential, ownership="focal_work",
        evidence=[ev("Faradaic efficiency was 92%")],
    )
    doc = CatalysisDocument(
        catalysts=[catalyst()], paper_types=["electrocatalysis"],
        electrocatalysis_experiments=[ElectrocatalysisExperiment(
            experiment_id="ec-1", catalyst_ref="cat-1", reaction=reaction("co2rr"),
            metrics=[metric], ownership="focal_work",
        )],
    )
    archive = assemble_catalysis_archive(doc, source_text=TEXT)
    conditions = archive.experiments[0].outputs[0].conditions
    assert conditions["reported_reference"] == "Ag/AgCl"
    assert conditions["reported_potential_raw"] == "-0.70 V vs Ag/AgCl"
    assert "converted_potential" not in conditions
    assert any("potential_not_converted" in item for item in archive.quality.semantic_warnings)

    potential.converted_potential = CatalysisQuantity(raw_value="0.26 V vs RHE", value=0.26, unit="V")
    potential.converted_reference = "RHE"
    potential.conversion_status = "deterministic"
    conservative = assemble_catalysis_archive(doc, source_text=TEXT)
    preserved = conservative.domain_payloads[0].values["validated_document"]["electrocatalysis_experiments"][0]["metrics"][0]["potential"]
    assert preserved.get("converted_potential") is None
    assert preserved["conversion_status"] == "rejected"


def test_normalization_bases_are_not_cross_compared_and_unknown_is_quarantined():
    geometric = NormalizationBasis(kind="geometric_area", reported_basis="geometric", comparison_status="comparable")
    ecsa = NormalizationBasis(kind="ecsa", reported_basis="ECSA", comparison_status="comparable")
    assert normalization_key(geometric) != normalization_key(ecsa)
    assert comparability_status(geometric, ecsa) == "not_comparable"
    metric = ElectrocatalyticMetric(
        property="partial_current_density", raw_value="10 mA/cm²", value=10, unit="mA/cm²",
        product="CO", normalization_basis=NormalizationBasis(kind="unknown"), ownership="focal_work",
        evidence=[ev("partial current density was 10 mA/cm²")],
    )
    doc = CatalysisDocument(catalysts=[catalyst()], electrocatalysis_experiments=[ElectrocatalysisExperiment(
        experiment_id="ec-1", catalyst_ref="cat-1", reaction=reaction("co2rr"), metrics=[metric], ownership="focal_work",
    )])
    archive = assemble_catalysis_archive(doc, source_text=TEXT)
    assert archive.experiments == []
    assert any(item["reason"] == "normalization_basis_unknown" for item in audit(archive)["quarantine"])


def test_product_metrics_and_tof_guardrails():
    basis = NormalizationBasis(kind="geometric_area", reported_basis="geometric", comparison_status="comparable")
    partial = ElectrocatalyticMetric(
        property="partial_current_density", raw_value="10 mA/cm²", value=10, unit="mA/cm²",
        product="CO", normalization_basis=basis, ownership="focal_work",
        evidence=[ev("partial current density was 10 mA/cm²")],
    )
    doc = CatalysisDocument(catalysts=[catalyst()], electrocatalysis_experiments=[ElectrocatalysisExperiment(
        experiment_id="ec-1", catalyst_ref="cat-1", reaction=reaction("co2rr"), metrics=[partial], ownership="focal_work",
    )])
    archive = assemble_catalysis_archive(doc, source_text=TEXT)
    assert archive.experiments[0].outputs[0].conditions["product"] == "CO"
    assert any(rel.predicate == "reports" for rel in archive.relationships)
    with pytest.raises(ValidationError, match="must identify its product"):
        ElectrocatalyticMetric(property="faradaic_efficiency", raw_value="92%", value=92, unit="%")
    tof = HeterogeneousMetric(
        property="turnover_frequency", raw_value="2 s-1", value=2, unit="s-1",
        normalization_basis=basis, ownership="focal_work", evidence=[ev("2 s-1")],
    )
    tof_archive = assemble_catalysis_archive(hetero_doc(tof), source_text=TEXT + "\nThe TOF was 2 s-1.")
    assert any(item["reason"] == "incompatible_unit_basis" for item in audit(tof_archive)["quarantine"])


def test_conversion_selectivity_distinction_derived_and_conflict_quarantine():
    selectivity = HeterogeneousMetric(
        property="selectivity", raw_value="75%", value=75, unit="%", product="CO2",
        ownership="focal_work", evidence=[ev("selectivity was 75%")],
    )
    derived = HeterogeneousMetric(
        property="yield", raw_value="61.5%", value=61.5, unit="%", product="CO2",
        ownership="focal_work", derivation={"reported_property":"conversion and selectivity","reported_raw_value":"82% and 75%","transformation":"conversion * selectivity"},
        evidence=[ev("CO conversion was 82%")],
    )
    doc = hetero_doc()
    doc.heterogeneous_experiments[0].metrics.extend([selectivity, derived])
    text = TEXT + "\nCO2 selectivity was 75%."
    archive = assemble_catalysis_archive(doc, source_text=text)
    properties = {item.property for item in archive.experiments[0].outputs}
    assert {"conversion", "selectivity"} <= properties and "yield" not in properties
    assert any(item["reason"] == "derived_value_not_reported" for item in audit(archive)["quarantine"])
    conflict = CatalysisConditionConflict(
        field="temperature", record_ref="exp-1",
        reported_values=[{"raw_value":"300 °C"},{"raw_value":"350 °C"}],
    )
    blocked = assemble_catalysis_archive(hetero_doc(conflicts=[conflict]), source_text=TEXT)
    assert blocked.experiments == []
    assert any(item["reason"] == "condition_conflict" for item in audit(blocked)["quarantine"])


def test_stability_conditions_and_catalyst_states_remain_separate():
    stability_metric = ElectrocatalyticMetric(
        property="retention", raw_value="90%", value=90, unit="%", ownership="focal_work",
        evidence=[ev("retained activity was 90%")],
    )
    fresh = catalyst()
    spent = catalyst("cat-spent", "spent", "cat-1")
    doc = hetero_doc(catalysts=[fresh, spent])
    doc.stability_tests = [StabilityTest(
        stability_id="stab-1", experiment_ref="exp-1", mode="time_on_stream",
        duration=CatalysisQuantity(raw_value="10 h", value=10, unit="h"),
        retained_metric=stability_metric, ownership="focal_work",
        evidence=[ev("retained activity was 90% after 10 h at 300 °C")],
    )]
    archive = assemble_catalysis_archive(doc, source_text=TEXT)
    assert len([item for item in archive.materials if "catalyst" in item.tags]) == 2
    assert any(rel.predicate == "derived_from" for rel in archive.relationships)
    stability = next(item for item in archive.experiments if item.experiment_type == "catalyst_stability")
    assert stability.outputs[0].conditions["duration"]["raw_value"] == "10 h"


def test_dft_maps_only_to_calculation_record():
    metric = ComputationalMetric(
        property="adsorption_free_energy", raw_value="-0.24 eV", value=-0.24, unit="eV",
        adsorbate_or_intermediate="H*", ownership="focal_work",
        evidence=[ev("adsorption free energy of -0.24 eV")],
    )
    doc = CatalysisDocument(
        catalysts=[catalyst()], paper_types=["computational_dft"],
        calculations=[CatalysisCalculation(
            calculation_id="dft-1", material_refs=["cat-1"], code="VASP", functional="PBE",
            outputs=[metric], ownership="focal_work", evidence=[ev("using PBE")],
        )],
    )
    archive = assemble_catalysis_archive(doc, source_text=TEXT)
    assert len(archive.calculations) == 1
    assert archive.experiments == []
    assert archive.calculations[0].outputs[0].property == "adsorption_free_energy"


def test_text_only_and_source_bundle_provenance_and_pipeline_dedicated_path(monkeypatch):
    text_only = assemble_catalysis_archive(hetero_doc(), source_text=TEXT)
    assert text_only.sources[0].checksum is None
    source_bundle = bundle()
    bundled = assemble_catalysis_archive(hetero_doc(), source_text=source_bundle.page_marked_text(), source_bundle=source_bundle)
    assert bundled.sources[0].checksum == "abc123"
    assert bundled.domain_payloads[0].values["source_context"]["source_id"] == "src-fixture"

    class FakeExtractor:
        model = "offline-fake"
        def __init__(self, **kwargs): pass
        def extract_text(self, text, source_bundle=None): return hetero_doc()

    import synthex_platform.extraction.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "CatalysisGeminiExtractor", FakeExtractor)
    route, archive = SynthexExtractionPipeline().extract_text(TEXT, domain="catalysis")
    assert route.domain == "catalysis"
    assert archive.metadata.domain == "catalysis"
    assert archive.domain_payloads[0].schema_version == "1.0-stage2"
