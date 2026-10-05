from __future__ import annotations

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.score_fatigue_c_raw import score_raw_fatigue_payload


def _measurement(property_name, raw, value, *, outcome, orientation="rolling", frequency=4000):
    return {
        "property": property_name, "raw_value": raw, "value": value,
        "conditions": [
            {"name": "orientation", "value": orientation},
            {"name": "frequency", "value": frequency, "unit": "RPM"},
            {"name": "stress_ratio", "value": -1},
            {"name": "failure_or_runout", "value": outcome},
            {"name": "scientific_type", "value": "reported_measurement"},
            *([{"name": "runout_cycles", "value": 10000000}] if outcome == "runout" else []),
        ],
        "source": {"table_id": "Table A2"},
    }


def test_provider_score_keeps_duplicate_amplitudes_and_runout_censored():
    _, gold, _ = load_locked_case("MECH-FATIGUE-C")
    payload = {
        "materials": [{"local_id": "m1", "name": "A37JC steel", "ownership": "focal_work"}],
        "experiments": [{
            "local_id": "e1", "material_id": "m1", "ownership": "focal_work",
            "measurements": [
                _measurement("stress_amplitude", "227.26", 227.26, outcome="failure"),
                _measurement("cycles_to_failure", "1,411,137", 1411137, outcome="failure"),
                _measurement("stress_amplitude", "227.26", 227.26, outcome="runout"),
            ],
        }],
    }
    score = score_raw_fatigue_payload(payload, gold)
    assert score["duplicate_227_26_observations"] == 2
    check = next(item for item in score["runout_checks"] if item["table"] == "A2" and item["table_row"] == 7)
    assert check["censoring_correct"] is True
    assert score["fatigue_limit_inventions"] == 0


def test_provider_score_rejects_runout_as_cycles_to_failure_and_flags_fatigue_limit():
    _, gold, _ = load_locked_case("MECH-FATIGUE-C")
    payload = {
        "materials": [{"local_id": "m1", "name": "A37JC steel", "ownership": "focal_work"}],
        "experiments": [{
            "local_id": "e1", "material_id": "m1", "ownership": "focal_work",
            "measurements": [
                _measurement("stress_amplitude", "222.67", 222.67, outcome="runout"),
                _measurement("cycles_to_failure", "10,000,000", 10000000, outcome="runout"),
                _measurement("fatigue_limit", "222.67", 222.67, outcome="runout"),
            ],
        }],
    }
    score = score_raw_fatigue_payload(payload, gold)
    check = next(item for item in score["runout_checks"] if item["table"] == "A2" and item["table_row"] == 1)
    assert check["censoring_correct"] is False
    assert score["fatigue_limit_inventions"] == 1
