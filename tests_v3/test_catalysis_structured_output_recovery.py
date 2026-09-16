from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.catalysis_extractor import (
    MAX_CATALYSIS_REPAIR_ATTEMPTS,
    CatalysisGeminiExtractor,
    CatalysisStructuredExtractionValidationError,
    catalysis_output_contract,
    normalize_catalysis_document_structure,
    parse_catalysis_document_json,
)
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.extraction import pipeline as pipeline_module


SOURCE_TEXT = """--- PAGE 1 ---
MMONiCo + Ce was evaluated for CO2 methanation in a fixed-bed reactor.
The CO2 conversion was approximately 85% after 1400 min at 350 °C.
"""


def _bundle() -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-gold-a",
            filename="1-s2.0-S0360319924005640-main.pdf",
            source_checksum="gold-a-checksum",
        ),
        pages=[SourcePageContext(
            page=1,
            native_text=SOURCE_TEXT,
            text=SOURCE_TEXT,
            native_parser="pypdf",
            parser="pypdf",
            origin="native_text",
            sufficient=True,
        )],
    )


def _malformed_gold_a_shape() -> dict:
    """Representative old-contract errors from the 115-error real Gold A response."""
    return {
        "source": {
            "title": "Improved conversion, selectivity, and stability during CO2 methanation",
            "source_id": "src-gold-a",
        },
        "paper_types": "heterogeneous_catalysis",
        "scope_status": "in_scope",
        "catalysts": [{"name": "MMONiCo + Ce", "chemical_formula": "Mg4.7NiCo0.3Al2O9 + 0.3CeO2"}],
        "preparations": [{"material_ref": "MMONiCo + Ce", "steps": [{"process": "calcination", "parameters": {"temperature": "500 °C"}}]}],
        "characterizations": [{"catalyst_id": "MMONiCo + Ce", "properties": [{"name": "surface area", "value": 20.1}]}],
        "heterogeneous_experiments": [{
            "catalyst_id": "MMONiCo + Ce",
            "reaction": "CO2 methanation",
            "conditions": {"temperature": "350 °C"},
            "performance_metrics": [{"property": "conversion", "value": 85, "unit": "%"}],
        }],
        "stability_tests": [{"catalyst_id": "MMONiCo + Ce", "time": "1400 min", "temperature": "350 °C"}],
    }


def _valid_repaired_payload() -> dict:
    evidence = [{
        "source_id": "src-gold-a",
        "page": 1,
        "text_snippet": "The CO2 conversion was approximately 85% after 1400 min at 350 °C.",
        "source_type": "text",
        "original_source_type": "native_text",
    }]
    return {
        "source": {"title": "Improved conversion, selectivity, and stability during CO2 methanation"},
        "paper_types": ["heterogeneous_catalysis", "stability_deactivation"],
        "scope_status": "supported",
        "catalysts": [{
            "local_id": "cat_mmonico_ce",
            "reported_name": "MMONiCo + Ce",
            "state": "as_synthesized",
            "ownership": "focal_work",
            "evidence": evidence,
        }],
        "heterogeneous_experiments": [{
            "experiment_id": "exp_co2_methanation",
            "catalyst_ref": "cat_mmonico_ce",
            "reaction": {
                "reported_reaction": "CO2 methanation",
                "reaction_class": "hydrogenation",
                "reactants": [{"reported_name": "CO2", "formula": "CO2"}],
                "products": [{"reported_name": "CH4", "formula": "CH4"}],
            },
            "temperature": {"raw_value": "350 °C", "value": 350, "unit": "°C", "qualifier": "exact"},
            "metrics": [{
                "property": "conversion",
                "raw_value": "approximately 85%",
                "value": 85,
                "unit": "%",
                "qualifier": "approx",
                "reactant": "CO2",
                "ownership": "focal_work",
                "evidence": evidence,
            }],
            "ownership": "focal_work",
            "evidence": evidence,
        }],
        "stability_tests": [{
            "stability_id": "stability_mmonico_ce",
            "experiment_ref": "exp_co2_methanation",
            "mode": "time_on_stream",
            "duration": {"raw_value": "1400 min", "value": 1400, "unit": "min", "qualifier": "exact"},
            "operating_temperature": {"raw_value": "350 °C", "value": 350, "unit": "°C", "qualifier": "exact"},
            "ownership": "focal_work",
            "evidence": evidence,
        }],
    }


class _FakeModels:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.outputs.pop(0))


def _extractor(outputs: list[str]) -> CatalysisGeminiExtractor:
    extractor = CatalysisGeminiExtractor.__new__(CatalysisGeminiExtractor)
    extractor.registry = DomainRegistry()
    extractor.api_key = "offline"
    extractor.model = "offline-catalysis"
    extractor.client = SimpleNamespace(models=_FakeModels(outputs))
    return extractor


def test_actual_contract_is_derived_from_strict_pydantic_models():
    contract = catalysis_output_contract()
    serialized = json.dumps(contract)
    assert "CatalysisDocument" not in serialized  # descriptive title noise is removed
    assert '"local_id"' in serialized and '"experiment_id"' in serialized
    assert '"additionalProperties": false' in serialized
    assert MAX_CATALYSIS_REPAIR_ATTEMPTS == 1


def test_safe_normalization_handles_only_deterministic_cases():
    malformed = _malformed_gold_a_shape()
    normalized = normalize_catalysis_document_structure(malformed, _bundle())
    assert "source_id" not in normalized["source"]
    assert normalized["scope_status"] == "supported"
    assert normalized["paper_types"] == ["heterogeneous_catalysis"]
    assert "name" in normalized["catalysts"][0]
    assert "local_id" not in normalized["catalysts"][0]
    assert normalized["heterogeneous_experiments"][0]["reaction"] == "CO2 methanation"
    with pytest.raises(ValidationError):
        parse_catalysis_document_json(json.dumps(malformed), source_bundle=_bundle())


def test_safe_normalization_accepts_only_observed_exact_paper_type_typo():
    payload = _valid_repaired_payload()
    payload["paper_types"] = ["catalyst_character_characterization"]
    document = parse_catalysis_document_json(json.dumps(payload), source_bundle=_bundle())
    assert document.paper_types == ["catalyst_characterization"]

    payload["paper_types"] = ["characterization"]
    with pytest.raises(ValidationError):
        parse_catalysis_document_json(json.dumps(payload), source_bundle=_bundle())


def test_pipeline_metadata_is_stripped_only_when_authoritatively_verified():
    valid = _valid_repaired_payload()
    valid["source"].update({
        "source_id": "src-gold-a",
        "filename": "1-s2.0-S0360319924005640-main.pdf",
        "source_checksum": "gold-a-checksum",
    })
    assert parse_catalysis_document_json(json.dumps(valid), source_bundle=_bundle()).source.title
    valid["source"]["source_checksum"] = "wrong"
    with pytest.raises(ValidationError) as caught:
        parse_catalysis_document_json(json.dumps(valid), source_bundle=_bundle())
    assert any(error["loc"][-1] == "source_checksum" for error in caught.value.errors())
    valid = _valid_repaired_payload()
    valid["source"]["unexpected_scientific_field"] = "must fail"
    with pytest.raises(ValidationError):
        parse_catalysis_document_json(json.dumps(valid), source_bundle=_bundle())


def test_exact_evidence_string_can_become_minimal_verified_native_object():
    valid = _valid_repaired_payload()
    snippet = "The CO2 conversion was approximately 85% after 1400 min at 350 °C."
    valid["heterogeneous_experiments"][0]["metrics"][0]["evidence"] = [snippet]
    document = parse_catalysis_document_json(json.dumps(valid), source_bundle=_bundle())
    evidence = document.heterogeneous_experiments[0].metrics[0].evidence[0]
    assert evidence.text_snippet == snippet
    assert evidence.page == 1 and evidence.source_id == "src-gold-a"
    assert evidence.original_source_type == "native_text"
    assert evidence.evidence_strength == "verified_native"


def test_unsupported_evidence_string_remains_invalid_instead_of_being_guessed():
    valid = _valid_repaired_payload()
    valid["stability_tests"][0]["evidence"] = ["not present in source"]
    with pytest.raises(ValidationError):
        parse_catalysis_document_json(json.dumps(valid), source_bundle=_bundle())


def test_invalid_gold_a_shape_invokes_exactly_one_repair_and_validates():
    extractor = _extractor([
        json.dumps(_malformed_gold_a_shape()),
        json.dumps(_valid_repaired_payload()),
    ])
    document = extractor.extract_text(SOURCE_TEXT, source_bundle=_bundle())
    calls = extractor.client.models.calls
    assert len(calls) == 2
    assert document.catalysts[0].local_id == "cat_mmonico_ce"
    assert "EXACT PYDANTIC ERRORS" in calls[1]["contents"]
    assert "ACTUAL CATALYSIS PYDANTIC CONTRACT" in calls[1]["contents"]
    assert "Repair schema structure only" in calls[1]["contents"]
    assert "Do not invent scientific values" in calls[1]["contents"]
    assert calls[0]["config"]["temperature"] == 0 and calls[0]["config"]["seed"] == 0
    assert "response_json_schema" not in calls[1]["config"]


def test_persistent_invalid_output_fails_cleanly_after_one_repair():
    malformed = json.dumps(_malformed_gold_a_shape())
    extractor = _extractor([malformed, malformed])
    with pytest.raises(CatalysisStructuredExtractionValidationError) as caught:
        extractor.extract_text(SOURCE_TEXT, source_bundle=_bundle())
    error = caught.value
    assert len(extractor.client.models.calls) == 2
    assert error.route == "catalysis" and error.source_id == "src-gold-a"
    assert error.repair_attempted is True and error.validation_errors
    assert len(error.raw_output_reference) == 64
    assert "115" not in str(error)
    assert str(error) == "Catalysis extraction could not be validated. No invalid scientific records were admitted."


def test_streamlit_handles_typed_catalysis_failure_without_raw_response_dump():
    app_source = (Path(__file__).resolve().parents[1] / "platform_app.py").read_text(encoding="utf-8")
    public_source = app_source.split('elif page == "Developer · Battery validation":', 1)[0]
    assert "CatalysisStructuredExtractionValidationError" in public_source
    assert 'context="extraction_validation"' in public_source
    assert '"status": notice.status' in public_source
    assert '"message": notice.message' in public_source
    assert '"message": str(exc)' not in public_source
    assert "debug_payload" not in app_source
    assert "raw_response_excerpt" not in app_source


def test_pipeline_preserves_catalysis_call_diagnostics_on_provider_failure(monkeypatch):
    class FailingExtractor:
        model = "offline"
        last_diagnostics = {
            "gemini_calls": 1,
            "repair_calls": 0,
            "schema_valid_first_response": False,
            "schema_valid_repaired_response": False,
            "persistent_failure": False,
        }

        def __init__(self, **_kwargs):
            pass

        def extract_text(self, *_args, **_kwargs):
            raise RuntimeError("transport failed")

    monkeypatch.setattr(pipeline_module, "CatalysisGeminiExtractor", FailingExtractor)
    pipeline = pipeline_module.SynthexExtractionPipeline()
    with pytest.raises(RuntimeError, match="transport failed"):
        pipeline.extract_text("catalysis", domain="catalysis")
    assert pipeline.last_extraction_diagnostics["gemini_calls"] == 1
