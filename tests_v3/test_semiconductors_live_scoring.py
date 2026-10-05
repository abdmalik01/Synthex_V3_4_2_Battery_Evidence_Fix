from __future__ import annotations

import json

import pytest

from benchmark.semiconductors_v1.score_persisted_raw import _physical_value, score_raw_case
from benchmark.semiconductors_v1.source_tables import ROOT, source_lock


def _gold(case_id: str) -> dict:
    lock = source_lock(case_id)
    return json.loads((ROOT / lock["gold_file"]).read_text(encoding="utf-8"))


def test_scaled_source_unit_and_declared_normalization_must_agree():
    item = {"raw_value": "1.36", "unit": "×10^20 cm^-3", "normalized_value": 1.36e20}
    assert _physical_value(item) == pytest.approx(1.36e20)
    item["normalized_value"] = 1.36e19
    assert _physical_value(item) is None


def test_pdf_flattened_scientific_notation_is_independently_parsed():
    assert _physical_value({"raw_value": "1.4 × 1019", "parsed_value": 1.4e19,
                            "unit": "cm^-3"}) == 1.4e19


def test_raw_scoring_keeps_value_recovery_separate_from_property_fidelity():
    raw = {
        "materials": [{"local_id": "m1", "formula": "ZnO", "ownership": "focal_work"}],
        "derived_properties": [{
            "property_key": "carrier_mobility", "raw_value": "21.4", "unit": "cm^2/V/s",
            "material_ref": "m1", "ownership": "focal_work",
            "evidence": [{"source_type": "table", "locator": "row=1;column=4"}],
        }],
    }
    score = score_raw_case(raw, _gold("SEM-GOLD-A"))
    assert score["exact_value_and_unit_points"] == 1
    assert score["exact_property_key_points"] == 0  # Hall specificity was lost.
    assert score["table_locator_points"] == 1
    assert score["canonical_admission_not_implied"] is True


def test_transport_scoring_does_not_invent_missing_dash_cells():
    raw = {
        "materials": [{"local_id": "m1", "name": "Undoped ZnO film", "ownership": "focal_work"}],
        "properties": [{
            "canonical_key": "carrier_concentration", "raw_value": "1.4 × 1019",
            "parsed_value": 1.4e19, "unit": "cm^-3", "material_ref": "m1",
            "conditions": {"sample": "undoped as-grown", "measurement_temperature": "room temperature"},
        }],
    }
    score = score_raw_case(raw, _gold("SEM-TRANSPORT-B"))
    assert score["exact_value_and_unit_points"] == 1
    assert score["expected_points"] == 46
    assert score["missing_dash_cells_not_zero_filled"] is True
