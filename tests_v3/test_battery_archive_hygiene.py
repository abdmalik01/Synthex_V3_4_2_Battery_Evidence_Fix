from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_postprocess import apply_scientific_guardrails
from synthex_platform.extraction.battery_assembler import assemble_battery_archive


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


def test_c_rate_definition_is_categorical_condition_not_numeric_result():
    snippet = "For electrochemical testing, 1 C = 300 mA/g."
    source_text = f"--- PAGE 1 ---\n{snippet}"
    doc = BatteryDocument.model_validate({
        "source": {"title": "C-rate definition fixture"},
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "g1",
            "ownership": "focal_work",
            "electrochemical_testing": {
                "c_rate_definition": "1 C = 300 mA/g",
                "evidence": [{
                    "page": 1,
                    "source_type": "text",
                    "text_snippet": snippet,
                }],
            },
        }],
    })

    archive = assemble_battery_archive(doc, model="offline-test", source_text=source_text)
    performance_experiment = next(
        experiment for experiment in archive.experiments
        if experiment.experiment_type == "battery performance / cycling"
    )
    c_rate = next(
        condition for condition in performance_experiment.conditions
        if condition.property == "c_rate_definition"
    )

    assert c_rate.raw_value == "1 C = 300 mA/g"
    assert c_rate.value == "1 C = 300 mA/g"
    assert c_rate.unit is None
    assert c_rate.qualifier == "categorical"
    assert all(output.property != "c_rate_definition" for output in performance_experiment.outputs)
