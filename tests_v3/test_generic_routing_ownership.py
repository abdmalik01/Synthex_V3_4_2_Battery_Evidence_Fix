from __future__ import annotations

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument
from synthex_platform.extraction.router import DomainRouter


def test_matkg_style_text_uses_generic_materials_informatics_fallback():
    text = """
    MatKG is an autonomously generated knowledge graph for materials science.
    We use named entity recognition, BERT, RDF triples, SPARQL, an ontology and a literature-mining corpus.
    Catalyst entities, TiO2, Fe2O3, CdTe and graphene are examples drawn from cited literature and a database.
    """
    route = DomainRouter().route_text(text)
    assert route.domain == "generic"
    assert route.ambiguity_reason == "materials_informatics_signals"
    assert "knowledge graph" in route.matched_terms["generic"]


def test_focal_catalysis_experiment_is_not_suppressed_by_generic_safety():
    text = """
    We synthesized a NiFe catalyst and measured oxygen evolution reaction activity.
    Reaction conditions were 1.0 M KOH; the overpotential was 280 mV at 10 mA cm-2.
    Tafel slope and Faradaic efficiency were measured in our electrochemical experiment.
    """
    route = DomainRouter().route_text(text)
    assert route.domain == "catalysis"
    assert route.ambiguity_reason is None
    assert route.focal_signals["catalysis"]


def test_nonfocal_generic_objects_are_quarantined_not_admitted():
    evidence = Evidence(page=2, text_snippet="TiO2 is an example from cited literature.")
    draft = ExtractedDocument(
        source=DraftSource(title="MatKG"),
        materials=[DraftMaterial(local_id="tio2", formula="TiO2", ownership="example", evidence=[evidence])],
        experiments=[DraftExperiment(
            local_id="catalysis_example", experiment_type="catalysis", material_refs=["tio2"],
            outputs=[Measurement(property="overpotential", raw_value="300 mV", value=300, unit="mV", evidence=[evidence])],
            ownership="cited_prior_work", evidence=[evidence],
        )],
        domain_values={"materials_informatics": {"entity_examples": ["TiO2", "Fe2O3", "CdTe", "graphene"]}},
    )
    archive = assemble_archive(draft, domain="generic", model="test")
    assert archive.materials == [] and archive.experiments == []
    values = archive.domain_payloads[0].values
    assert values["materials_informatics"]["entity_examples"][0] == "TiO2"
    reasons = {item["reason"] for item in values["admissibility"]["quarantined_objects"]}
    assert reasons == {"ownership_example", "ownership_cited_prior_work"}
