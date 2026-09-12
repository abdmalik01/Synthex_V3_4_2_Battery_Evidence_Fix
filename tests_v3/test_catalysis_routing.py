from __future__ import annotations

from synthex_platform.extraction.router import DomainRouter


def test_contextual_heterogeneous_catalysis_routes_and_classifies():
    route = DomainRouter().route_text("""
    We prepared a Pt/Al2O3 catalyst and tested CO oxidation in a fixed-bed reactor.
    CO conversion and CO2 selectivity were measured as a function of temperature at a defined GHSV.
    """)
    assert route.domain == "catalysis"
    assert "heterogeneous_catalysis" in route.paper_types
    assert "heterogeneous_context" in route.focal_signals["catalysis"]


def test_contextual_electrocatalysis_routes_and_classifies():
    route = DomainRouter().route_text("""
    A NiFe catalyst was evaluated for OER in 1.0 M KOH using an Ag/AgCl reference electrode.
    The overpotential at 10 mA cm-2, Tafel slope, and Faradaic efficiency were measured.
    """)
    assert route.domain == "catalysis"
    assert "electrocatalysis" in route.paper_types
    assert "electrocatalysis_context" in route.focal_signals["catalysis"]


def test_contextual_computational_catalysis_routes_and_classifies():
    route = DomainRouter().route_text("""
    Density functional theory calculations used a surface slab with adsorbate intermediates.
    We report adsorption free energy, activation barrier, and d-band center for the catalyst surface.
    """)
    assert route.domain == "catalysis"
    assert "computational_dft" in route.paper_types
    assert "computational_catalysis_context" in route.focal_signals["catalysis"]


def test_review_and_deferred_subtype_are_identified_without_claiming_full_support():
    review = DomainRouter().route_text("""
    This review summarizes catalytic CO oxidation, conversion, selectivity, reactor operation,
    and turnover frequency across supported catalysts.
    """)
    assert review.domain == "catalysis"
    assert "review" in review.paper_types

    deferred = DomainRouter().route_text("""
    We studied photocatalysis with a photocatalyst for CO oxidation and measured conversion,
    selectivity, reactor feed composition, and time on stream.
    """)
    assert deferred.domain == "catalysis"
    assert deferred.scope_status == "deferred_subtype"


def test_incidental_catalyst_matkg_and_battery_controls_do_not_misroute():
    incidental = DomainRouter().route_text("The database cites a catalyst as an example from prior work.")
    assert incidental.domain == "generic"

    matkg = DomainRouter().route_text("""
    A materials knowledge graph uses named entity recognition, BERT, RDF triples, SPARQL,
    ontology, corpus literature mining, and catalyst examples from cited literature.
    """)
    assert matkg.domain == "generic"
    assert matkg.ambiguity_reason == "materials_informatics_signals"

    battery = DomainRouter().route_text("""
    Lithium-ion batteries were assembled in coin cells with cathode, anode, electrolyte,
    charge-discharge cycling, capacity retention, and electrochemical impedance spectroscopy.
    """)
    assert battery.domain == "batteries"
