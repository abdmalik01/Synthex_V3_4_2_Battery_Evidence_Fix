import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError

from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_extractor import BatteryGeminiExtractor
from synthex_platform.extraction.battery_models import (
    BatteryDocument,
    BatteryEvidence,
    BatteryGroup,
    BatteryMaterial,
    BatteryPerformancePoint,
    BatteryQuantity,
    CellAssembly,
    ElectrodeFabrication,
    ElectrochemicalTesting,
    ImpedanceProtocol,
)
from synthex_platform.extraction.battery_postprocess import (
    apply_scientific_guardrails,
    deduplicate_shared_protocols,
)


class _SequencedModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(text=outcome)


def _extractor_with(outcomes):
    extractor = object.__new__(BatteryGeminiExtractor)
    extractor.model = "test-model"
    extractor.requested_model = "test-model"
    extractor.fallback_models = ["fallback-1", "fallback-2", "fallback-3"]
    extractor.provider_mode = "production"
    extractor.last_provider_audit = {}
    models = _SequencedModels(outcomes)
    extractor.client = SimpleNamespace(models=models)
    return extractor, models


def test_transient_gemini_and_network_errors_fail_over_once_per_model():
    outcomes = [
        errors.ServerError(503, {"error": {"message": "unavailable"}}),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        json.dumps({"source": {"title": "Recovered"}}),
    ]
    extractor, models = _extractor_with(outcomes)

    doc = extractor.extract_text("paper")

    assert doc.source.title == "Recovered"
    assert len(models.calls) == 4
    assert [call["model"] for call in models.calls] == [
        "test-model", "fallback-1", "fallback-2", "fallback-3",
    ]
    assert models.calls[-1]["config"]["temperature"] == 0
    assert models.calls[-1]["config"]["seed"] == 0
    assert extractor.last_provider_audit["fallback_occurred"] is True


def test_deterministic_request_error_is_not_retried():
    extractor, models = _extractor_with([ValueError("bad request")])
    with pytest.raises(ValueError, match="bad request"):
        extractor.extract_text("paper")
    assert len(models.calls) == 1


def test_local_validation_error_is_not_retried():
    extractor, models = _extractor_with(["{not-json}"])
    with pytest.raises(RuntimeError, match="failed local Pydantic validation"):
        extractor.extract_text("paper")
    assert len(models.calls) == 1


def test_unknown_scientific_field_is_rejected_instead_of_silently_dropped():
    with pytest.raises(ValidationError, match="unmodeled_scientific_result"):
        BatteryDocument.model_validate({
            "battery_groups": [{
                "group_id": "g1",
                "unmodeled_scientific_result": {"value": 42, "unit": "mAh/g"},
            }],
        })


def test_recognized_active_material_role_is_preserved_without_inferring_polarity():
    material = BatteryMaterial(material_id="m1", formula="Li2FeTiO4", role="active_material")
    assert material.role == "active_material"


def test_recognized_legacy_alias_is_mapped_before_strict_validation():
    doc = BatteryDocument.model_validate({
        "shared_protocols": [{
            "protocol_id": "p1",
            "electrode_fabrication": {"loading": "1.0 mg/cm2"},
        }],
    })
    assert doc.shared_protocols[0].electrode_fabrication.mass_loading.value == 1.0


def test_unlabeled_drying_operations_get_structural_ids_without_data_loss():
    doc = BatteryDocument.model_validate({
        "shared_protocols": [{
            "protocol_id": "p1",
            "electrode_fabrication": {
                "drying_steps": [
                    {"temperature": "80 C", "duration": "12 h", "atmosphere": "vacuum"},
                    {"temperature": "120 C", "duration": "6 h", "atmosphere": "vacuum"},
                ],
            },
        }],
    })
    steps = doc.shared_protocols[0].electrode_fabrication.drying_steps
    assert [step.step for step in steps] == ["drying_1", "drying_2"]
    assert [step.temperature.value for step in steps] == [80.0, 120.0]
    assert [step.duration.value for step in steps] == [12.0, 6.0]


def test_misnested_pressing_pressure_is_promoted_but_conflicts_are_rejected():
    payload = {
        "shared_protocols": [{
            "protocol_id": "p1",
            "electrode_fabrication": {
                "drying_steps": [{
                    "step": "press",
                    "details": "Pressed using a hydraulic press.",
                    "pressing_pressure": "10 MPa",
                }],
            },
        }],
    }
    doc = BatteryDocument.model_validate(payload)
    fabrication = doc.shared_protocols[0].electrode_fabrication
    assert fabrication.pressing_pressure.value == 10.0
    assert fabrication.drying_steps[0].details == "Pressed using a hydraulic press."

    payload["shared_protocols"][0]["electrode_fabrication"]["pressing_pressure"] = "20 MPa"
    with pytest.raises(ValidationError, match="pressing_pressure"):
        BatteryDocument.model_validate(payload)


def test_performance_point_preserves_qualifier_and_all_evidence_in_archive():
    point = BatteryPerformancePoint.model_validate({
        "property": "capacity retention",
        "raw_value": "~89.2%",
        "value": 89.2,
        "unit": "%",
        "ownership": "focal_work",
        "evidence": [
            {"page": 10, "text_snippet": "approximately 89.2% retention"},
            {"page": 11, "text_snippet": "retention after 100 cycles was about 89.2%"},
        ],
    })
    doc = BatteryDocument(battery_groups=[BatteryGroup(
        group_id="700C", ownership="focal_work", performance_points=[point]
    )])

    source_text = (
        "--- PAGE 10 ---\napproximately 89.2% retention\n"
        "--- PAGE 11 ---\nretention after 100 cycles was about 89.2%"
    )
    archive = assemble_battery_archive(doc, model="test", source_text=source_text)
    measurement = next(o for e in archive.experiments for o in e.outputs)

    assert point.qualifier == "approx"
    assert measurement.qualifier == "approx"
    assert len(point.evidence) == 2
    assert len(measurement.evidence) == 2


def test_invalid_quantity_qualifier_remains_unknown():
    quantity = BatteryQuantity.model_validate({
        "raw_value": "24 C", "value": 24.0, "unit": "C", "qualifier": "ambient"
    })
    assert quantity.qualifier == "unknown"


def test_ambiguous_precursor_ratio_note_does_not_propose_a_correction():
    doc = BatteryDocument(
        materials=[BatteryMaterial(
            material_id="m1",
            synthesis={"precursor_ratio_raw": "2.05.1:1"},
        )],
        extraction_notes=[
            "The ratio 2.05.1:1 probably means 2.05:1:1 and was a typo."
        ],
    )

    cleaned = apply_scientific_guardrails(doc)

    assert cleaned.materials[0].synthesis.precursor_ratio_raw == "2.05.1:1"
    assert not any("probably means" in note for note in cleaned.extraction_notes)
    assert any("no corrected ratio was inferred" in note for note in cleaned.extraction_notes)


def test_repeated_extended_protocols_are_deduplicated_without_merging_differences():
    evidence = [BatteryEvidence(page=2, text_snippet="shared protocol")]
    common = {
        "electrode_fabrication": ElectrodeFabrication(active_material="LFP", evidence=evidence),
        "cell_assembly": CellAssembly(cell_format="CR2032", evidence=evidence),
        "electrochemical_testing": ElectrochemicalTesting(long_term_cycles=100, evidence=evidence),
    }
    doc = BatteryDocument(battery_groups=[
        BatteryGroup(group_id="a", variant_label="600 C", **common),
        BatteryGroup(group_id="b", variant_label="700 C", **common),
        BatteryGroup(
            group_id="c",
            variant_label="800 C",
            electrode_fabrication=ElectrodeFabrication(active_material="NMC", evidence=evidence),
            cell_assembly=common["cell_assembly"],
            electrochemical_testing=common["electrochemical_testing"],
        ),
    ])

    result = deduplicate_shared_protocols(doc)

    assert result.battery_groups[0].electrode_fabrication is None
    assert result.battery_groups[1].electrode_fabrication is None
    assert result.battery_groups[2].electrode_fabrication.active_material == "NMC"
    assert all(group.cell_assembly is None for group in result.battery_groups)
    assert all(group.electrochemical_testing is None for group in result.battery_groups)


def test_eis_output_has_one_canonical_experiment_location():
    point = BatteryPerformancePoint(
        property="charge_transfer_resistance",
        raw_value="1258.6 ohm",
        value=1258.6,
        unit="ohm",
        method="EIS",
        ownership="focal_work",
        evidence=[BatteryEvidence(page=11, text_snippet="Rct value (1258.6 ohm)")],
    )
    doc = BatteryDocument(battery_groups=[BatteryGroup(
        group_id="700C",
        ownership="focal_work",
        impedance_protocol=ImpedanceProtocol(method="EIS"),
        performance_points=[point],
    )])

    archive = assemble_battery_archive(
        doc, model="test", source_text="--- PAGE 11 ---\nRct value (1258.6 ohm)"
    )
    locations = [
        experiment.experiment_type
        for experiment in archive.experiments
        for output in experiment.outputs
        if output.property == "charge_transfer_resistance"
    ]
    assert locations == ["EIS"]
