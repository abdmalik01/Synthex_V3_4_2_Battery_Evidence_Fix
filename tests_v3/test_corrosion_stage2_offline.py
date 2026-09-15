from __future__ import annotations

from synthex_platform.extraction.corrosion_admission import decide_corrosion_metric_admission
from synthex_platform.extraction.corrosion_evidence import (
    verify_corrosion_document_evidence,
    verify_corrosion_evidence_item,
)
from synthex_platform.extraction.corrosion_models import (
    CorrosionDocument,
    CorrosionEnvironment,
    CorrosionEvidence,
    CorrosionExperiment,
    CorrosionMaterial,
    CorrosionMetric,
    CorrosionQuantity,
    CorrosionSource,
    PolarizationConditions,
)
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


SNIPPET = "The corrosion current density decreased to 2.4 µA cm−2 in 3.5 wt.% NaCl."


def _bundle() -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-corrosion",
            filename="corrosion.pdf",
            source_checksum="checksum-corrosion",
        ),
        pages=[SourcePageContext(
            page=4,
            native_text=f"Results\n{SNIPPET}\nEcorr was -0.42 V vs Ag/AgCl.",
            text=f"Results\n{SNIPPET}\nEcorr was -0.42 V vs Ag/AgCl.",
            native_parser="pypdf",
            parser="pypdf",
            origin="native_text",
            sufficient=True,
        )],
    )


def _metric(property_name: str = "corrosion_current_density", *, ownership: str = "focal_work") -> CorrosionMetric:
    return CorrosionMetric(
        property=property_name,
        quantity=CorrosionQuantity(raw_value="2.4 µA cm−2", value=2.4, unit="µA cm−2", qualifier="exact"),
        ownership=ownership,
        evidence=[CorrosionEvidence(text_snippet=SNIPPET, source_type="text")],
    )


def test_exact_native_evidence_is_verified_without_provider_calls():
    verified = verify_corrosion_evidence_item(_metric().evidence[0], _bundle())
    assert verified.verbatim_match is True
    assert verified.source_id == "src-corrosion"
    assert verified.page == 4
    assert verified.original_source_type == "native_text"


def test_missing_or_ambiguous_evidence_is_not_fabricated():
    missing = CorrosionEvidence(text_snippet="not in this source", source_type="text")
    checked = verify_corrosion_evidence_item(missing, _bundle())
    assert checked.verbatim_match is False
    assert checked.source_id is None


def test_document_evidence_verification_preserves_scientific_values():
    document = CorrosionDocument(
        source=CorrosionSource(title="Corrosion study"),
        paper_types=["polarization_corrosion"],
        materials=[CorrosionMaterial(local_id="mat_1", reported_name="AA7075", ownership="focal_work")],
        environments=[CorrosionEnvironment(environment_id="env_1", electrolyte="3.5 wt.% NaCl")],
        experiments=[CorrosionExperiment(
            experiment_id="exp_1",
            experiment_type="potentiodynamic_polarization",
            material_refs=["mat_1"],
            environment_ref="env_1",
            polarization_conditions=PolarizationConditions(reference_electrode="Ag/AgCl"),
            metrics=[_metric()],
            ownership="focal_work",
        )],
    )
    verified = verify_corrosion_document_evidence(document, _bundle())
    metric = verified.experiments[0].metrics[0]
    assert metric.quantity.value == 2.4
    assert metric.quantity.unit == "µA cm−2"
    assert metric.evidence[0].verbatim_match is True


def test_focal_verified_numeric_metric_is_admitted():
    metric = _metric().model_copy(update={
        "evidence": [verify_corrosion_evidence_item(_metric().evidence[0], _bundle())]
    })
    decision = decide_corrosion_metric_admission(
        metric,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode="Ag/AgCl",
        treatment_present=False,
        unresolved_conflict=False,
    )
    assert decision.admitted is True
    assert decision.reason is None


def test_cited_unverified_and_conflicted_values_are_quarantined():
    cited = _metric(ownership="cited_prior_work")
    assert decide_corrosion_metric_admission(
        cited,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode="Ag/AgCl",
        treatment_present=False,
        unresolved_conflict=False,
    ).reason == "ownership_cited_prior_work"

    unverified = _metric()
    assert decide_corrosion_metric_admission(
        unverified,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode="Ag/AgCl",
        treatment_present=False,
        unresolved_conflict=False,
    ).reason == "no_verified_value_specific_evidence"

    verified = _metric().model_copy(update={
        "evidence": [verify_corrosion_evidence_item(_metric().evidence[0], _bundle())]
    })
    assert decide_corrosion_metric_admission(
        verified,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode="Ag/AgCl",
        treatment_present=False,
        unresolved_conflict=True,
    ).reason == "unresolved_condition_conflict"


def test_potential_metric_requires_reported_reference_electrode():
    metric = CorrosionMetric(
        property="corrosion_potential",
        quantity=CorrosionQuantity(raw_value="-0.42 V", value=-0.42, unit="V", qualifier="exact"),
        ownership="focal_work",
        evidence=[verify_corrosion_evidence_item(
            CorrosionEvidence(text_snippet="Ecorr was -0.42 V vs Ag/AgCl.", source_type="text"),
            _bundle(),
        )],
    )
    decision = decide_corrosion_metric_admission(
        metric,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode=None,
        treatment_present=False,
        unresolved_conflict=False,
    )
    assert decision.admitted is False
    assert decision.reason == "missing_reference_electrode"


def test_eis_and_efficiency_semantics_are_conservative():
    verified = _metric("charge_transfer_resistance").model_copy(update={
        "evidence": [verify_corrosion_evidence_item(_metric().evidence[0], _bundle())]
    })
    wrong_test = decide_corrosion_metric_admission(
        verified,
        scope_status="supported",
        experiment_type="potentiodynamic_polarization",
        reference_electrode="Ag/AgCl",
        treatment_present=False,
        unresolved_conflict=False,
    )
    assert wrong_test.reason == "eis_metric_outside_eis_experiment"

    efficiency = _metric("inhibition_efficiency").model_copy(update={
        "evidence": [verify_corrosion_evidence_item(_metric().evidence[0], _bundle())]
    })
    no_treatment = decide_corrosion_metric_admission(
        efficiency,
        scope_status="supported",
        experiment_type="weight_loss",
        reference_electrode=None,
        treatment_present=False,
        unresolved_conflict=False,
    )
    assert no_treatment.reason == "missing_linked_treatment"
