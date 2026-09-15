from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_postprocess import apply_scientific_guardrails


def test_numeric_synthesis_step_label_becomes_ordered_label_not_process_name():
    doc = BatteryDocument.model_validate({
        "materials": [{
            "material_id": "m1",
            "ownership": "focal_work",
            "synthesis": {
                "method": "sol-gel",
                "steps": [{"step": "1", "details": "Mixed at room temperature"}],
            },
        }],
    })

    guarded = apply_scientific_guardrails(doc)

    assert guarded.materials[0].synthesis.steps[0].step == "synthesis step 1"
    assert any("numeric synthesis step label '1'" in note for note in guarded.extraction_notes)


def test_unitless_warburg_coefficient_is_preserved_raw_but_not_canonically_numeric():
    doc = BatteryDocument.model_validate({
        "battery_groups": [{
            "group_id": "g1",
            "ownership": "focal_work",
            "performance_points": [{
                "property": "warburg_coefficient",
                "raw_value": "637.7",
                "value": 637.7,
                "unit": None,
                "qualifier": "exact",
                "ownership": "focal_work",
            }],
        }],
    })

    guarded = apply_scientific_guardrails(doc)
    point = guarded.battery_groups[0].performance_points[0]

    assert point.raw_value == "637.7"
    assert point.value is None
    assert point.unit is None
    assert point.qualifier == "unknown"
    assert any("unitless warburg_coefficient '637.7'" in note for note in guarded.extraction_notes)


def test_unitful_warburg_coefficient_remains_numeric():
    doc = BatteryDocument.model_validate({
        "battery_groups": [{
            "group_id": "g1",
            "ownership": "focal_work",
            "performance_points": [{
                "property": "warburg_coefficient",
                "raw_value": "637.7 ohm s^-1/2",
                "value": 637.7,
                "unit": "ohm s^-1/2",
                "qualifier": "exact",
                "ownership": "focal_work",
            }],
        }],
    })

    guarded = apply_scientific_guardrails(doc)
    point = guarded.battery_groups[0].performance_points[0]

    assert point.value == 637.7
    assert point.unit == "ohm s^-1/2"
