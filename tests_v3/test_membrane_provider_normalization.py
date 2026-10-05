import copy
from hashlib import sha256
import json

import pytest

from benchmark.membranes_v1.provider_normalization import (
    NORMALIZER_VERSION,
    normalize_provider_payload,
)
from benchmark.membranes_v1.raw_scoring import score_raw_case
from benchmark.membranes_v1.recover_cases import CASE_DIR, recover_gold_a
from synthex_platform.extraction.assembler import assemble_archive


def _gold(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _a_payload() -> dict:
    return {
        "materials": [{
            "local_id": "material_3", "name": "Pure Matrimid membrane",
            "material_type": "membrane", "composition": "Matrimid 5218",
            "ownership": "focal_work", "evidence": "pure Matrimid membrane",
        }],
        "processes": [],
        "experiments": [{
            "local_id": "experiment_1", "experiment_type": "gas permeation",
            "conditions": {"feed": "CO2/CH4 (1:1 volume ratio)", "temperature": "25 C", "transmembrane_pressure": "3 bar"},
            "material_refs": ["material_3"], "ownership": "focal_work",
            "evidence": "mixed gas at 3 bar and 25 C",
        }],
        "derived_properties": [
            {
                "property_key": "gas_permeability", "raw_value": "6.8", "canonical_value": 6.8,
                "units": "Barrer", "material_ref": "material_3", "experiment_ref": "experiment_1",
                "conditions": {"species": "CO2", "test_mode": "mixed-gas", "temperature": "25 C"},
                "ownership": "focal_work", "evidence": "6.8 Barrer",
                "source_reference": {"source_type": "table", "table_id": "Table 1", "locator": "row=5;column=1"},
            },
            {
                "property_key": "gas_permeability", "raw_value": "0.16", "canonical_value": 0.16,
                "units": "Barrer", "material_ref": "material_3", "experiment_ref": "experiment_1",
                "conditions": {"species": "CH4", "test_mode": "mixed-gas", "temperature": "25 C"},
                "ownership": "focal_work", "evidence": "0.16 Barrer",
                "source_reference": {"source_type": "table", "table_id": "Table 1", "locator": "row=5;column=4"},
            },
            {
                "property_key": "mixed_gas_selectivity", "raw_value": "42", "canonical_value": 42.0,
                "units": "dimensionless", "material_ref": "material_3", "experiment_ref": "experiment_1",
                "conditions": {"species_pair": "CO2/CH4", "test_mode": "mixed-gas", "temperature": "25 C", "feed_composition": "1:1 volume ratio"},
                "ownership": "focal_work", "evidence": "42 selectivity",
                "source_reference": {"source_type": "table", "table_id": "Table 1", "locator": "row=5;column=7"},
            },
        ],
    }


def _b_payload(*, ownership: str | None = "focal_work") -> dict:
    material = {
        "local_id": "material_1", "name": "Matrimid 5218", "category": "polymer",
        "composition": "Matrimid 5218 polymer", "evidence": "Matrimid 5218",
    }
    experiment = {
        "local_id": "experiment_1", "type": "gas permeation",
        "material_refs": ["material_1"], "conditions": "30 C and 1 bar",
        "evidence": "gas permeation at 30 C and 1 bar",
    }
    if ownership is not None:
        material["ownership"] = ownership
        experiment["ownership"] = ownership
    return {
        "materials": [material], "processes": [], "experiments": [experiment],
        "derived_or_reported_properties": [
            {
                "property_key": "gas_permeability", "material_ref": "material_1", "experiment_ref": "experiment_1",
                "raw_value": "1.5", "value": 1.5, "unit": "Barrer",
                "conditions": {"species": "O2", "test_mode": "pure gas", "temperature": "30 C", "pressure_kind": "1 bar"},
                "evidence": "O2 | 1.5 (M membrane)",
            },
            {
                "property_key": "ideal_selectivity", "material_ref": "material_1", "experiment_ref": "experiment_1",
                "raw_value": "7.5", "value": 7.5, "unit": "dimensionless",
                "conditions": {"species_pair": "O2/N2", "test_mode": "pure gas", "temperature": "30 C"},
                "evidence": "M | 7.5 (O2/N2)",
            },
            {
                "property_key": "membrane_thickness", "material_ref": "material_1", "experiment_ref": None,
                "raw_value": "99 ± 1", "value": 99.0, "unit": "um",
                "conditions": {"thickness_scope": "whole membrane"}, "evidence": "M (99 ± 1)",
            },
        ],
    }


def _serialized(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def test_raw_payload_is_unchanged_by_normalization():
    raw = _a_payload()
    before = sha256(_serialized(raw)).hexdigest()
    normalize_provider_payload(raw, case_id="MEM-GOLD-A")
    assert sha256(_serialized(raw)).hexdigest() == before


def test_normalized_candidate_is_separate_object():
    raw = _a_payload()
    candidate, _ = normalize_provider_payload(raw, case_id="MEM-GOLD-A")
    assert candidate.model_dump(mode="json") != raw
    assert "derived_properties" in raw


def test_value_count_cannot_increase_without_raw_property_object():
    raw = _b_payload()
    candidate, audit = normalize_provider_payload(raw, case_id="MEM-SEP-B")
    assert sum(len(item.outputs) for item in candidate.experiments) == 2
    assert audit["normalized_output_count"] <= audit["raw_property_object_count"]


def test_missing_pressure_is_not_invented_for_selectivity():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    outputs = candidate.experiments[0].outputs
    permeability = next(item for item in outputs if item.property == "gas_permeability")
    selectivity = next(item for item in outputs if item.property == "ideal_selectivity")
    assert permeability.conditions["feed_pressure"] == 1.0
    assert "feed_pressure" not in selectivity.conditions
    assert "pressure_kind" not in selectivity.conditions


def test_missing_locator_is_not_invented():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    evidence = candidate.experiments[0].outputs[0].evidence[0]
    assert evidence.page is None and evidence.table_id is None and evidence.locator is None
    assert evidence.verbatim_match is None


def test_ownership_is_not_invented():
    candidate, _ = normalize_provider_payload(_b_payload(ownership=None), case_id="MEM-SEP-B")
    assert candidate.materials[0].ownership == "unknown"
    assert candidate.experiments[0].ownership == "unknown"


def test_species_identity_is_preserved():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    permeability = next(item for item in candidate.experiments[0].outputs if item.property == "gas_permeability")
    assert permeability.conditions["species"] == "O2"


def test_gas_pair_identity_is_preserved():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    selectivity = next(item for item in candidate.experiments[0].outputs if item.property == "ideal_selectivity")
    assert selectivity.conditions["species_pair"] == "O2/N2"


def test_permeability_does_not_become_permeance():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    assert {item.property for item in candidate.experiments[0].outputs} == {"gas_permeability", "ideal_selectivity"}


def test_ideal_selectivity_does_not_become_mixed_gas_selectivity():
    candidate, _ = normalize_provider_payload(_b_payload(), case_id="MEM-SEP-B")
    selectivity = next(item for item in candidate.experiments[0].outputs if "selectivity" in item.property)
    assert selectivity.property == "ideal_selectivity"
    assert selectivity.conditions["test_mode"] == "pure_gas"


def test_deterministic_result_is_independent_of_normalization():
    before = sum(len(item.outputs) for item in recover_gold_a().experiments)
    normalize_provider_payload(_a_payload(), case_id="MEM-GOLD-A")
    after = sum(len(item.outputs) for item in recover_gold_a().experiments)
    assert before == after == 12


def test_historical_raw_scoring_is_unchanged():
    raw = _a_payload()
    before = score_raw_case(copy.deepcopy(raw), _gold("gold_a.json"))
    normalize_provider_payload(raw, case_id="MEM-GOLD-A")
    after = score_raw_case(raw, _gold("gold_a.json"))
    assert before == after


def test_normalizer_version_is_auditable():
    candidate, audit = normalize_provider_payload(_a_payload(), case_id="MEM-GOLD-A")
    assert audit["normalizer_version"] == NORMALIZER_VERSION
    assert candidate.domain_values["normalizer_version"] == NORMALIZER_VERSION


def test_normalized_candidate_cannot_bypass_scientific_contract():
    candidate, _ = normalize_provider_payload(_a_payload(), case_id="MEM-GOLD-A")
    archive = assemble_archive(candidate, domain="membranes", model=NORMALIZER_VERSION)
    assert not archive.experiments
    assert sum(len(item.outputs) for item in archive.experiments) == 0
    assert archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def test_normalization_fails_safely_for_unknown_case():
    with pytest.raises(ValueError, match="Unsupported membrane normalization case"):
        normalize_provider_payload(_a_payload(), case_id="MEM-UNKNOWN")
