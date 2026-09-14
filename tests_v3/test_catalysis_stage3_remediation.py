from __future__ import annotations

import json
from types import SimpleNamespace

from benchmark_catalysis_gold import contextual_value_match
from benchmark_catalysis_remediation import load_remediation_gold, normalization_source_review
from benchmark_catalysis_stage3 import _observed_metrics
from synthex_platform.extraction.catalysis_assembler import assemble_catalysis_archive
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.catalysis_extractor import CatalysisGeminiExtractor, parse_catalysis_document_json
from synthex_platform.extraction.catalysis_models import (
    CatalysisDocument,
    CatalysisEvidence,
    CatalysisQuantity,
    CatalystMaterial,
    ElectrochemicalPotential,
    ElectrocatalysisExperiment,
    ElectrocatalyticMetric,
    FeedComponent,
    HeterogeneousCatalysisExperiment,
    HeterogeneousMetric,
    NormalizationBasis,
    ReactionDefinition,
)
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


SOURCE = """--- PAGE 1 ---
CO2 and O2 were supplied together. Methane onset was -0.75 V RHE.
The n-propanol partial current density was 0.5 mA cm-2 at -0.75 V RHE, normalized by geometric electrode area.
With pure CO2, methane onset was -0.95 V RHE.
The material containing Co experienced better CO2 conversions (~80 % at 350 °C) than that containing Fe (50 % at 350 °C).
"""


def _evidence(snippet: str) -> list[CatalysisEvidence]:
    return [CatalysisEvidence(page=1, text_snippet=snippet, original_source_type="native_text")]


def _potential(raw: str, value: float) -> ElectrochemicalPotential:
    return ElectrochemicalPotential(
        raw_potential=CatalysisQuantity(raw_value=raw, value=value, unit="V"),
        reported_reference="RHE",
    )


def _catalyst() -> CatalystMaterial:
    return CatalystMaterial(
        local_id="cat-cu", reported_name="commercial polycrystalline Cu powder",
        ownership="focal_work", evidence=_evidence("CO2 and O2 were supplied together"),
    )


def _reaction() -> ReactionDefinition:
    return ReactionDefinition(reported_reaction="CO2 reduction", reaction_class="co2rr")


def test_electrocatalysis_feed_is_typed_and_scalar_shape_is_boundedly_normalized():
    payload = {
        "electrocatalysis_experiments": [{
            "experiment_id": "ec-o2",
            "reaction": {"reaction_class": "co2rr"},
            "feed_composition": {"species": "CO2"},
        }],
    }
    document = parse_catalysis_document_json(json.dumps(payload))
    assert document.electrocatalysis_experiments[0].feed_composition == [FeedComponent(species="CO2")]


def test_parent_feed_is_inherited_by_metric_without_cross_condition_flattening():
    document = CatalysisDocument(
        catalysts=[_catalyst()],
        electrocatalysis_experiments=[
            ElectrocatalysisExperiment(
                experiment_id="ec-o2", catalyst_ref="cat-cu", reaction=_reaction(),
                feed_composition=[FeedComponent(species="CO2"), FeedComponent(species="O2")],
                ownership="focal_work", evidence=_evidence("CO2 and O2 were supplied together"),
                metrics=[ElectrocatalyticMetric(
                    property="onset_potential", raw_value="-0.75 V RHE", value=-0.75, unit="V",
                    product="methane", potential=_potential("-0.75 V RHE", -0.75),
                    ownership="focal_work", evidence=_evidence("Methane onset was -0.75 V RHE"),
                )],
            ),
            ElectrocatalysisExperiment(
                experiment_id="ec-pure", catalyst_ref="cat-cu", reaction=_reaction(),
                feed_composition=[FeedComponent(species="CO2")], ownership="focal_work",
                evidence=_evidence("With pure CO2, methane onset was -0.95 V RHE"),
                metrics=[ElectrocatalyticMetric(
                    property="onset_potential", raw_value="-0.95 V RHE", value=-0.95, unit="V",
                    product="methane", potential=_potential("-0.95 V RHE", -0.95),
                    ownership="focal_work", evidence=_evidence("methane onset was -0.95 V RHE"),
                )],
            ),
        ],
    )
    observed = _observed_metrics(document.model_dump(mode="json", exclude_none=True))
    assert {item["context"]["feed"] for item in observed} == {"O2-containing CO2 feed", "pure CO2"}
    o2_expected = {
        "property": "onset_potential", "value": -0.75, "unit": "V",
        "product": "methane", "potential": "-0.75 V RHE",
        "reference_electrode": "RHE", "context": {"feed": "O2-containing CO2 feed"},
    }
    assert any(contextual_value_match(o2_expected, item) for item in observed)
    assert not any(
        contextual_value_match({**o2_expected, "context": {"feed": "pure CO2"}}, item)
        for item in observed
    )


def test_assembler_preserves_parent_feed_with_product_potential_and_explicit_basis():
    metric = ElectrocatalyticMetric(
        property="partial_current_density", raw_value="0.5 mA cm-2", value=0.5, unit="mA cm-2",
        product="n-propanol", potential=_potential("-0.75 V RHE", -0.75),
        normalization_basis=NormalizationBasis(
            kind="geometric_area", reported_basis="geometric electrode area", comparison_status="comparable",
        ),
        ownership="focal_work",
        evidence=_evidence("The n-propanol partial current density was 0.5 mA cm-2 at -0.75 V RHE, normalized by geometric electrode area"),
    )
    document = CatalysisDocument(
        catalysts=[_catalyst()],
        electrocatalysis_experiments=[ElectrocatalysisExperiment(
            experiment_id="ec-o2", catalyst_ref="cat-cu", reaction=_reaction(),
            feed_composition=[FeedComponent(species="CO2"), FeedComponent(species="O2")],
            ownership="focal_work", evidence=_evidence("CO2 and O2 were supplied together"), metrics=[metric],
        )],
    )
    archive = assemble_catalysis_archive(document, source_text=SOURCE)
    conditions = archive.experiments[0].outputs[0].conditions
    assert [item["species"] for item in conditions["feed_composition"]] == ["CO2", "O2"]
    assert conditions["product"] == "n-propanol"
    assert conditions["reported_potential_raw"] == "-0.75 V RHE"
    assert conditions["normalization_basis"]["kind"] == "geometric_area"


def test_area_unit_does_not_infer_normalization_and_unknown_value_is_quarantined():
    metric = ElectrocatalyticMetric(
        property="partial_current_density", raw_value="0.5 mA cm-2", value=0.5, unit="mA cm-2",
        product="n-propanol", potential=_potential("-0.75 V RHE", -0.75),
        ownership="focal_work",
        evidence=_evidence("The n-propanol partial current density was 0.5 mA cm-2 at -0.75 V RHE"),
    )
    document = CatalysisDocument(
        catalysts=[_catalyst()],
        electrocatalysis_experiments=[ElectrocatalysisExperiment(
            experiment_id="ec-o2", catalyst_ref="cat-cu", reaction=_reaction(),
            feed_composition=[FeedComponent(species="CO2"), FeedComponent(species="O2")],
            ownership="focal_work", evidence=_evidence("CO2 and O2 were supplied together"), metrics=[metric],
        )],
    )
    archive = assemble_catalysis_archive(document, source_text=SOURCE)
    assert archive.experiments == []
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    assert any(item["reason"] == "normalization_basis_unknown" for item in audit["quarantine"])


def test_gold_a_explicit_native_prose_conversion_metrics_survive_strict_model():
    document = CatalysisDocument(
        catalysts=[
            CatalystMaterial(local_id="co", reported_name="MMONiCo"),
            CatalystMaterial(local_id="fe", reported_name="MMONiFe"),
        ],
        heterogeneous_experiments=[
            HeterogeneousCatalysisExperiment(
                experiment_id="co-exp", catalyst_ref="co",
                reaction=ReactionDefinition(reported_reaction="CO2 methanation", reaction_class="hydrogenation"),
                temperature=CatalysisQuantity(raw_value="350 °C", value=350, unit="°C"),
                metrics=[HeterogeneousMetric(
                    property="conversion", raw_value="~80 %", value=80, unit="%", qualifier="approx",
                    reactant="CO2", evidence=_evidence("CO2 conversions (~80 % at 350 °C)"),
                )],
            ),
            HeterogeneousCatalysisExperiment(
                experiment_id="fe-exp", catalyst_ref="fe",
                reaction=ReactionDefinition(reported_reaction="CO2 methanation", reaction_class="hydrogenation"),
                temperature=CatalysisQuantity(raw_value="350 °C", value=350, unit="°C"),
                metrics=[HeterogeneousMetric(
                    property="conversion", raw_value="50 %", value=50, unit="%", qualifier="exact",
                    reactant="CO2", evidence=_evidence("Fe (50 % at 350 °C)"),
                )],
            ),
        ],
    )
    assert [item.metrics[0].value for item in document.heterogeneous_experiments] == [80, 50]


def test_mocked_comparative_prose_preserves_both_catalyst_condition_metrics_end_to_end():
    snippet = (
        "Catalyst A experienced ~80 % CO2 conversion at 350 °C, "
        "while Catalyst B showed 50 % at 350 °C."
    )
    evidence = [{
        "source_id": "src-comparison", "page": 1, "text_snippet": snippet,
        "source_type": "text", "original_source_type": "native_text",
        "verbatim_match": True,
    }]
    output = {
        "source": {"title": "Comparative heterogeneous catalysis fixture"},
        "paper_types": ["heterogeneous_catalysis"],
        "scope_status": "supported",
        "catalysts": [
            {"local_id": "cat-a", "reported_name": "Catalyst A", "ownership": "focal_work", "evidence": evidence},
            {"local_id": "cat-b", "reported_name": "Catalyst B", "ownership": "focal_work", "evidence": evidence},
        ],
        "heterogeneous_experiments": [
            {
                "experiment_id": "exp-a", "catalyst_ref": "cat-a",
                "reaction": {"reported_reaction": "CO2 methanation", "reaction_class": "hydrogenation"},
                "temperature": {"raw_value": "350 °C", "value": 350, "unit": "°C", "qualifier": "exact"},
                "metrics": [{
                    "property": "conversion", "raw_value": "~80 %", "value": 80, "unit": "%",
                    "qualifier": "approx", "reactant": "CO2", "ownership": "focal_work", "evidence": evidence,
                }],
                "ownership": "focal_work", "evidence": evidence,
            },
            {
                "experiment_id": "exp-b", "catalyst_ref": "cat-b",
                "reaction": {"reported_reaction": "CO2 methanation", "reaction_class": "hydrogenation"},
                "temperature": {"raw_value": "350 °C", "value": 350, "unit": "°C", "qualifier": "exact"},
                "metrics": [{
                    "property": "conversion", "raw_value": "50 %", "value": 50, "unit": "%",
                    "qualifier": "exact", "reactant": "CO2", "ownership": "focal_work", "evidence": evidence,
                }],
                "ownership": "focal_work", "evidence": evidence,
            },
        ],
    }

    class FakeModels:
        def generate_content(self, **kwargs):
            assert "Do not return a merely representative subset" in kwargs["contents"]
            assert "expand every explicit comparison or ordered list" in kwargs["contents"]
            return SimpleNamespace(text=json.dumps(output))

    source_bundle = SourceBundle(
        source=SourceMetadata(source_id="src-comparison", filename="comparison.pdf", source_checksum="abc"),
        pages=[SourcePageContext(
            page=1, native_text=snippet, text=snippet, native_parser="pypdf", parser="pypdf",
            origin="native_text", sufficient=True,
        )],
    )
    extractor = CatalysisGeminiExtractor.__new__(CatalysisGeminiExtractor)
    extractor.registry = DomainRegistry()
    extractor.model = "offline-fake"
    extractor.client = SimpleNamespace(models=FakeModels())
    document = extractor.extract_text(source_bundle.page_marked_text(), source_bundle=source_bundle)

    observed = _observed_metrics(document.model_dump(mode="json", exclude_none=True))
    assert len(observed) == 2
    assert {(item["value"], item["context"]["catalyst"]) for item in observed} == {
        (80.0, "Catalyst A"), (50.0, "Catalyst B"),
    }
    assert document.heterogeneous_experiments[0].metrics[0].raw_value == "~80 %"
    assert document.heterogeneous_experiments[0].metrics[0].qualifier == "approx"
    assert all(item["property"] == "conversion" for item in observed)
    assert all(item["context"]["temperature"] == "350 °C" for item in observed)
    assert all(
        experiment.metrics[0].evidence[0].original_source_type == "native_text"
        for experiment in document.heterogeneous_experiments
    )

    archive = assemble_catalysis_archive(
        document, source_text=source_bundle.page_marked_text(), source_bundle=source_bundle,
    )
    assert len(archive.experiments) == 2
    assert sum(len(experiment.outputs) for experiment in archive.experiments) == 2
    for wrong in (
        {"context": {"catalyst": "Catalyst B", "temperature": "350 °C", "reaction": "hydrogenation"}},
        {"context": {"catalyst": "Catalyst A", "temperature": "400 °C", "reaction": "hydrogenation"}},
        {"property": "selectivity", "context": {"catalyst": "Catalyst A", "temperature": "350 °C"}},
    ):
        expected = {"property": "conversion", "value": 80, "unit": "%", **wrong}
        if wrong.get("property"):
            expected["property"] = wrong["property"]
        assert not any(contextual_value_match(expected, item) for item in observed)


def test_remediation_gold_overlay_leaves_historical_gold_semantics_separate():
    records = load_remediation_gold()
    adjusted = [
        item for item in records["CAT-GOLD-B"]["metrics"]
        if item["property"] == "partial_current_density"
    ]
    assert len(adjusted) == 2
    assert all("normalization_basis" not in item for item in adjusted)


def test_normalization_source_review_scores_unknown_as_scientifically_correct():
    document = {
        "catalysts": [{"local_id": "cu", "reported_name": "commercial polycrystalline Cu powder"}],
        "electrocatalysis_experiments": [
            {
                "experiment_id": "o2", "catalyst_ref": "cu",
                "reaction": {"reaction_class": "co2rr"},
                "feed_composition": [{"species": "CO2"}, {"species": "O2"}],
                "metrics": [{
                    "property": "partial_current_density", "value": 0.5, "unit": "mA cm-2",
                    "product": "n-propanol",
                    "potential": {"raw_potential": {"raw_value": "-0.75 V RHE", "unit": "V"}, "reported_reference": "RHE"},
                }],
            },
            {
                "experiment_id": "pure", "catalyst_ref": "cu",
                "reaction": {"reaction_class": "co2rr"},
                "feed_composition": [{"species": "CO2"}],
                "metrics": [{
                    "property": "partial_current_density", "value": 0.5, "unit": "mA cm-2",
                    "product": "n-propanol",
                    "potential": {"raw_potential": {"raw_value": "-1.00 V RHE", "unit": "V"}, "reported_reference": "RHE"},
                }],
            },
        ],
    }
    result = normalization_source_review(document)
    assert result["matched_count"] == result["expected_count"] == 2
