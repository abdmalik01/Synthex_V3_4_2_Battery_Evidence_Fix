from __future__ import annotations

from benchmark_catalysis_scoring_v2 import metric_match, reaction_equal, score_metric_association, unit_equal


def _observed_metric(**overrides):
    metric = {
        "property": "productivity",
        "raw_value": "168 mol CH4 h−1 L−1",
        "value": 168.0,
        "unit": "mol/L/h",
        "qualifier": "unknown",
        "product": "CH4",
        "reactant": None,
        "context": {
            "catalyst": "MMONiCo + Ce",
            "reaction": "CO2(g)+4H2(g) → CH4(g)+2H2O(l)",
            "temperature": "350 ◦C",
        },
    }
    for key, value in overrides.items():
        if key == "context":
            metric["context"] = {**metric["context"], **value}
        else:
            metric[key] = value
    return metric


def _expected_metric(**overrides):
    metric = {
        "property": "productivity",
        "value": 168,
        "unit": "mol CH4 h-1 L-1",
        "product": "CH4",
        "context": {
            "catalyst": "MMONiCo + Ce",
            "temperature": "350 °C",
            "reaction": "hydrogenation",
        },
    }
    for key, value in overrides.items():
        if key == "context":
            metric["context"] = {**metric["context"], **value}
        else:
            metric[key] = value
    return metric


def test_product_species_may_be_separated_from_equivalent_rate_unit():
    assert unit_equal(
        "mol CH4 h-1 L-1",
        "mol/L/h",
        expected_product="CH4",
        observed_product="CH4",
    )
    assert not unit_equal(
        "mol CH4 h-1 L-1",
        "mol/kg/s",
        expected_product="CH4",
        observed_product="CH4",
    )


def test_area_notation_equivalence_remains_supported():
    assert unit_equal("mA cm-2", "mA/cm2")


def test_explicit_co2_methanation_equation_matches_hydrogenation_class():
    assert reaction_equal("hydrogenation", "CO2(g)+4H2(g) → CH4(g)+2H2O(l)")
    assert reaction_equal("hydrogenation", "CO2 methanation")
    assert not reaction_equal("hydrogenation", "CO oxidation")


def test_metric_match_accepts_gold_a_productivity_representation():
    assert metric_match(_expected_metric(), _observed_metric())


def test_metric_match_still_rejects_wrong_catalyst_product_temperature_and_reaction():
    assert not metric_match(_expected_metric(), _observed_metric(context={"catalyst": "MMONiFe + Ce"}))
    assert not metric_match(_expected_metric(), _observed_metric(product="CO"))
    assert not metric_match(_expected_metric(), _observed_metric(context={"temperature": "400 °C"}))
    assert not metric_match(_expected_metric(), _observed_metric(context={"reaction": "CO oxidation"}))


def test_conversion_qualifier_is_preserved():
    expected = {
        "property": "conversion",
        "value": 80,
        "unit": "%",
        "qualifier": "approx",
        "reactant": "CO2",
        "context": {
            "catalyst": "MMONiCo",
            "temperature": "350 °C",
            "reaction": "hydrogenation",
        },
    }
    observed = {
        "property": "conversion",
        "value": 80.0,
        "unit": "%",
        "qualifier": "approx",
        "reactant": "CO2",
        "context": {
            "catalyst": "MMONiCo",
            "temperature": "350 ◦C",
            "reaction": "CO2(g)+4H2(g) → CH4(g)+2H2O(l)",
        },
    }
    assert metric_match(expected, observed)
    assert not metric_match(expected, {**observed, "qualifier": "exact"})


def test_full_gold_a_style_projection_scores_all_eight_without_weakening_associations():
    catalysts = [
        {"local_id": "a", "reported_name": "MMONiCo + Ce", "state": "unknown"},
        {"local_id": "b", "reported_name": "MMONiCo", "state": "unknown"},
        {"local_id": "c", "reported_name": "MMONi + Ce", "state": "unknown"},
        {"local_id": "d", "reported_name": "MMONiFe + Ce", "state": "unknown"},
        {"local_id": "e", "reported_name": "MMONi", "state": "unknown"},
        {"local_id": "f", "reported_name": "MMONiFe", "state": "unknown"},
    ]
    equation = {"reaction_class": "other_heterogeneous", "reported_reaction": "CO2(g)+4H2(g) → CH4(g)+2H2O(l)"}
    experiments = []
    productivity = [
        ("a", 168), ("b", 150), ("c", 148), ("d", 108), ("e", 105), ("f", 80),
    ]
    for catalyst_ref, value in productivity:
        experiments.append({
            "experiment_id": f"exp_{catalyst_ref}_{value}",
            "catalyst_ref": catalyst_ref,
            "reaction": equation,
            "temperature": {"raw_value": "350 ◦C"},
            "metrics": [{
                "property": "productivity", "value": float(value), "unit": "mol/L/h",
                "product": "CH4", "qualifier": "unknown",
            }],
        })
    experiments.append({
        "experiment_id": "conv_co",
        "catalyst_ref": "b",
        "reaction": equation,
        "temperature": {"raw_value": "350 ◦C"},
        "metrics": [{
            "property": "conversion", "value": 80.0, "unit": "%", "qualifier": "approx", "reactant": "CO2",
        }],
    })
    experiments.append({
        "experiment_id": "conv_fe",
        "catalyst_ref": "f",
        "reaction": equation,
        "temperature": {"raw_value": "350 ◦C"},
        "metrics": [{
            "property": "conversion", "value": 50.0, "unit": "%", "qualifier": "exact", "reactant": "CO2",
        }],
    })
    document = {"catalysts": catalysts, "heterogeneous_experiments": experiments, "electrocatalysis_experiments": []}
    gold = {
        "metrics": [
            {"property": "conversion", "value": 80, "unit": "%", "qualifier": "approx", "reactant": "CO2", "context": {"catalyst": "MMONiCo", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "conversion", "value": 50, "unit": "%", "qualifier": "exact", "reactant": "CO2", "context": {"catalyst": "MMONiFe", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 168, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONiCo + Ce", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 150, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONiCo", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 148, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONi + Ce", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 108, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONiFe + Ce", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 105, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONi", "temperature": "350 °C", "reaction": "hydrogenation"}},
            {"property": "productivity", "value": 80, "unit": "mol CH4 h-1 L-1", "product": "CH4", "context": {"catalyst": "MMONiFe", "temperature": "350 °C", "reaction": "hydrogenation"}},
        ]
    }
    score = score_metric_association(gold, document)
    assert score["matched_count"] == 8
    assert score["expected_count"] == 8
