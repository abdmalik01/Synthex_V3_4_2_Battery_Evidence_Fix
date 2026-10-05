from benchmark.membranes_v1.raw_scoring import score_raw_case
from benchmark.membranes_v1.recover_cases import CASE_DIR, recover_gold_a, recover_sep_b

import json


def _gold(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def test_deterministic_gold_a_is_exact_under_raw_scoring_contract():
    score = score_raw_case(recover_gold_a().model_dump(mode="json"), _gold("gold_a.json"))
    assert score["property_accuracy"]["exact_scientific_points"] == 12
    assert score["condition_association"]["exact_condition_points"] == 12
    assert score["unit_accuracy"]["exact_unit_points"] == 12


def test_deterministic_sep_b_is_exact_under_raw_scoring_contract():
    score = score_raw_case(recover_sep_b().model_dump(mode="json"), _gold("gold_sep_b.json"))
    assert score["property_accuracy"]["exact_scientific_points"] == 98
    assert score["condition_association"]["exact_condition_points"] == 98
    assert score["unit_accuracy"]["exact_unit_points"] == 98
    assert score["species_association"] == {
        "expected_species": 6,
        "exact_species": 6,
        "expected_gas_pairs": 8,
        "exact_gas_pairs": 8,
    }


def test_noncanonical_derived_properties_are_scored_without_admission():
    payload = {
        "materials": [{
            "local_id": "material_3", "name": "Pure Matrimid membrane",
            "composition": "Matrimid 5218", "ownership": "focal_work",
        }],
        "experiments": [{
            "local_id": "experiment_1", "material_refs": ["material_3"],
            "conditions": {
                "feed": "CO2/CH4 (1:1 volume ratio)", "temperature": "25 C",
                "transmembrane_pressure": "3 bar",
            },
            "ownership": "focal_work",
        }],
        "derived_properties": [{
            "property_key": "gas_permeability", "canonical_value": 6.8,
            "units": "Barrer", "material_ref": "material_3",
            "experiment_ref": "experiment_1", "ownership": "focal_work",
            "conditions": {"species": "CO2", "test_mode": "mixed-gas", "temperature": "25 C"},
            "source_reference": {"page": 6, "table_id": "Table 1", "locator": "row=5;column=1"},
            "evidence": "6.8 ± 0.3 Barrer",
        }],
    }
    score = score_raw_case(payload, _gold("gold_a.json"))
    assert score["raw_output_count"] == 1
    assert score["property_accuracy"]["exact_scientific_points"] == 1
    assert score["condition_association"]["exact_condition_points"] == 1
    assert score["evidence"]["with_table_or_locator"] == 1
    assert score["evidence"]["with_page_and_table_or_locator"] == 1
