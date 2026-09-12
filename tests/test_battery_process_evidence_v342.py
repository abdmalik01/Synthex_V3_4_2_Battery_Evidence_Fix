from synthex_platform.extraction.battery_models import BatteryDocument
from synthex_platform.extraction.battery_assembler import assemble_battery_archive


def test_process_step_accepts_evidence_array_and_assembles():
    raw = {
        "source": {"title": "Example"},
        "paper_types": ["materials_synthesis"],
        "materials": [{
            "material_id": "m1",
            "name": "Example",
            "formula": "X",
            "role": "cathode",
            "ownership": "focal_work",
            "synthesis": {
                "method": "sol-gel",
                "precursors": ["A"],
                "steps": [{
                    "step": 1,
                    "temperature": {"raw_value": "65 °C", "value": 65, "unit": "°C", "qualifier": "exact"},
                    "duration": {"raw_value": "5 h", "value": 5, "unit": "h", "qualifier": "exact"},
                    "details": "heated",
                    "evidence": [{"page": 2, "section": "Methods", "text_snippet": "heated at 65 °C for 5 h"}]
                }]
            }
        }]
    }
    doc = BatteryDocument.model_validate(raw)
    assert doc.materials[0].synthesis.steps[0].step == "1"
    assert len(doc.materials[0].synthesis.steps[0].evidence) == 1
    archive = assemble_battery_archive(
        doc,
        model="test",
        source_text=f"--- PAGE 2 ---\n{doc.materials[0].synthesis.steps[0].evidence[0].text_snippet}",
    )
    assert archive.processes
    assert archive.processes[0].evidence


def test_process_step_accepts_singleton_evidence_for_backward_compatibility():
    raw = {
        "source": {"title": "Example"},
        "materials": [{
            "material_id": "m1",
            "synthesis": {"steps": [{"step": "mix", "evidence": "mixed for 2 h"}]}
        }]
    }
    doc = BatteryDocument.model_validate(raw)
    ev = doc.materials[0].synthesis.steps[0].evidence
    assert len(ev) == 1
    assert ev[0].text_snippet == "mixed for 2 h"


def test_scientific_guardrails_remove_qualitative_temperature_guess_and_flag_non_atmosphere():
    from synthex_platform.extraction.battery_postprocess import apply_scientific_guardrails
    raw = {
        "source": {"title": "Example"},
        "materials": [{
            "material_id": "m1",
            "synthesis": {"steps": [{
                "step": 1,
                "temperature": {"raw_value": "room temperature", "value": 25, "unit": "°C", "qualifier": "approx"},
                "atmosphere": "water bath"
            }]}
        }]
    }
    doc = BatteryDocument.model_validate(raw)
    cleaned = apply_scientific_guardrails(doc)
    step = cleaned.materials[0].synthesis.steps[0]
    assert step.temperature.value is None
    assert step.atmosphere is None
    assert any("unsupported numeric temperature" in note for note in cleaned.extraction_notes)
    assert any("apparatus/heating medium" in note for note in cleaned.extraction_notes)
