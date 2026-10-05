from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_negative_h import recover_negative_h
from benchmark.mechanical_v1.score_negative_h import score_negative_h
from synthex_platform.extraction.router import DomainRouter
import pytest


def test_negative_h_routes_to_batteries_without_mechanical_contamination():
    _, gold, lock = load_locked_case("MECH-NEGATIVE-H")
    archive, first, second, text = recover_negative_h()
    score = score_negative_h(archive, first, second, text, gold)
    assert score["passed"] == score["total"] == lock["assertions"] == 10
    assert score["route"] == "batteries"
    assert score["misleading_vocabulary_detected"] == gold["misleading_vocabulary"]
    assert score["canonical_experiments"] == 0
    assert score["canonical_calculations"] == 0
    assert score["canonical_metrics"] == 0
    assert score["analytics_contamination_count"] == 0
    assert score["graph_contamination_count"] == 0


def test_generic_mechanical_words_alone_do_not_create_mechanical_route():
    text = "The cell experienced stress, strain, load, resistance, and eventual failure during service."
    with pytest.raises(ValueError, match="No supported materials-science domain"):
        DomainRouter().route_text(text)


def test_strong_mechanical_method_output_pair_still_routes_mechanical():
    text = "We performed a tensile test and measured yield strength, ultimate tensile strength, and elongation."
    route = DomainRouter().route_text(text)
    assert route.domain == "mechanical"
    assert "tensile_context" in route.focal_signals["mechanical"]
