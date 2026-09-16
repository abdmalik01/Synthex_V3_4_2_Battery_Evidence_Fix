import json

from synthex_platform.export import project_results_rows
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_models import BatteryDocument


def _evidence(text: str) -> dict:
    return {
        "page": 1,
        "source_type": "text",
        "text_snippet": text,
        "verbatim_match": True,
    }


def test_soc_and_synthesis_temperature_reach_analytics_without_inference():
    synthesis_sentence = "The LFP sample was synthesized hydrothermally at 200 °C for 6 h."
    result_sentence = "At 50% SOC the sample delivered 130 mAh g-1."
    doc = BatteryDocument.model_validate({
        "source": {"title": "Multidimensional battery fixture"},
        "paper_types": ["materials_synthesis", "electrochemical_performance"],
        "materials": [{
            "material_id": "mat-lfp-200",
            "name": "LFP 200",
            "formula": "LiFePO4",
            "role": "cathode",
            "ownership": "focal_work",
            "synthesis": {
                "method": "hydrothermal",
                "steps": [{
                    "step": "hydrothermal treatment",
                    "temperature": {"raw_value": "200 °C", "value": 200, "unit": "°C", "qualifier": "exact"},
                    "duration": {"raw_value": "6 h", "value": 6, "unit": "h", "qualifier": "exact"},
                    "evidence": [_evidence(synthesis_sentence)],
                }],
                "evidence": [_evidence(synthesis_sentence)],
            },
            "evidence": [_evidence(synthesis_sentence)],
        }],
        "battery_groups": [{
            "group_id": "group-lfp-200",
            "ownership": "focal_work",
            "battery_ids": ["cell-lfp-200"],
            "material_ref": "mat-lfp-200",
            "variant_label": "200 °C",
            "chemistry": "LFP",
            "performance_points": [{
                "property": "specific_capacity",
                "raw_value": "130 mAh g-1",
                "value": 130,
                "unit": "mAh g-1",
                "qualifier": "exact",
                "ownership": "focal_work",
                "additional_conditions": [{
                    "property": "SOC",
                    "raw_value": "50% SOC",
                    "value": 50,
                    "unit": "%",
                    "qualifier": "exact",
                    "evidence": [_evidence(result_sentence)],
                }],
                "evidence": [_evidence(result_sentence)],
            }],
            "evidence": [_evidence(result_sentence)],
        }],
    })

    assert doc.battery_groups[0].performance_points[0].additional_conditions[0].property == "state_of_charge"

    archive = assemble_battery_archive(doc)
    rows = project_results_rows(archive)
    result = next(row for row in rows if row["measurement_role"] == "result" and row["metric"] == "specific_capacity")
    conditions = json.loads(result["conditions_json"])

    assert conditions["state_of_charge"]["raw_value"] == "50% SOC"
    assert conditions["state_of_charge"]["value"] == 50.0
    assert conditions["state_of_charge"]["unit"] == "%"
    assert conditions["state_of_charge"]["evidence"][0]["verbatim_match"] is True

    assert conditions["synthesis_temperature"]["raw_value"] == "200 °C"
    assert conditions["synthesis_temperature"]["value"] == 200.0
    assert conditions["synthesis_temperature"]["unit"] == "°C"
    assert conditions["synthesis_temperature"]["evidence"][0]["verbatim_match"] is True


def test_unverified_additional_condition_is_not_promoted_to_canonical_context():
    result_sentence = "The sample delivered 130 mAh g-1."
    doc = BatteryDocument.model_validate({
        "source": {"title": "Unverified condition fixture"},
        "paper_types": ["electrochemical_performance"],
        "battery_groups": [{
            "group_id": "group-control",
            "ownership": "focal_work",
            "battery_ids": ["cell-control"],
            "performance_points": [{
                "property": "specific_capacity",
                "raw_value": "130 mAh g-1",
                "value": 130,
                "unit": "mAh g-1",
                "qualifier": "exact",
                "ownership": "focal_work",
                "additional_conditions": [{
                    "property": "SOC",
                    "raw_value": "50% SOC",
                    "value": 50,
                    "unit": "%",
                    "qualifier": "exact",
                    "evidence": [{
                        "page": 1,
                        "source_type": "text",
                        "text_snippet": "unrelated text",
                        "verbatim_match": False,
                    }],
                }],
                "evidence": [_evidence(result_sentence)],
            }],
            "evidence": [_evidence(result_sentence)],
        }],
    })

    archive = assemble_battery_archive(doc)
    result = next(
        row for row in project_results_rows(archive)
        if row["measurement_role"] == "result" and row["metric"] == "specific_capacity"
    )
    # The exporter intentionally encodes an empty condition mapping as an empty
    # string. Treat that representation as {} for the semantic assertion below.
    conditions = json.loads(result["conditions_json"] or "{}")
    assert "state_of_charge" not in conditions
