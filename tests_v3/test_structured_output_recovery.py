from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from synthex_platform.extraction.domain_extractor import (
    DomainGeminiExtractor,
    StructuredExtractionValidationError,
    normalize_extracted_document_structure,
    parse_extracted_document_json,
)
from synthex_platform.extraction.pipeline import SynthexExtractionPipeline
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


GAS_TEXT = """ZnO-xNiO gas sensors were fabricated and tested with CO and H2.
Gas response, selectivity, discriminability, operating temperature, and Ra/Rg - 1 were measured.
The total flow rate through the electric furnace was maintained at 500 mL/min.
The applied voltage was 5 V."""


def malformed_payload():
    return {
        "source": {"title": "Gas-sensing fixture"},
        "materials": [{"local_id": "material_1", "name": "ZnO-xNiO", "evidence": "ZnO-xNiO gas sensors"}],
        "processes": [{"local_id": "process_1", "evidence": "fabricated"}],
        "experiments": [
            {"local_id": "experiment_1", "evidence": "CO response"},
            {"local_id": "experiment_2", "evidence": "H2 response"},
        ],
    }


def repaired_payload():
    evidence = [{"source_type": "text", "text_snippet": "ZnO-xNiO gas sensors were fabricated"}]
    return {
        "source": {"title": "Gas-sensing fixture"},
        "materials": [{"local_id": "material_1", "name": "ZnO-xNiO", "ownership": "focal_work", "evidence": evidence}],
        "processes": [{"local_id": "process_1", "name": "fabrication", "ownership": "focal_work", "evidence": evidence}],
        "experiments": [
            {
                "local_id": "experiment_1", "experiment_type": "chemiresistive gas sensing",
                "ownership": "focal_work", "material_refs": ["material_1"], "target": "CO", "evidence": evidence,
            }
        ],
    }


def pipeline_source_fields():
    return {
        "source_id": "src-gas",
        "filename": "gas.pdf",
        "source_checksum": "gas-checksum",
    }


def condition_payload():
    payload = repaired_payload()
    payload["source"].update(pipeline_source_fields())
    payload["experiments"][0]["conditions"] = [
        {
            "property": "total_flow_rate",
            "raw_value": "500 mL/min",
            "value": 500,
            "unit": "mL/min",
            "evidence": ["total flow rate through the electric furnace was maintained at 500 mL/min"],
        },
        {
            "property": "applied_voltage",
            "raw_value": "5 V",
            "value": 5,
            "unit": "V",
            "evidence": ["applied voltage was 5 V"],
        },
    ]
    return payload


def _bundle():
    return SourceBundle(
        source=SourceMetadata(source_id="src-gas", filename="gas.pdf", source_checksum="gas-checksum"),
        pages=[SourcePageContext(
            page=1, native_text=GAS_TEXT, text=GAS_TEXT, native_parser="pypdf",
            parser="pypdf", origin="native_text", sufficient=True,
        )],
    )


def _extractor(responses):
    class FakeModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text=responses[len(self.calls) - 1])

    extractor = DomainGeminiExtractor.__new__(DomainGeminiExtractor)
    from synthex_platform.core.registry import DomainRegistry
    extractor.registry = DomainRegistry()
    extractor.model = "offline-fake"
    extractor.client = SimpleNamespace(models=FakeModels())
    return extractor


def test_safe_structural_normalization_wraps_known_singletons_without_inference():
    normalized = normalize_extracted_document_structure(malformed_payload())
    assert normalized["materials"][0]["evidence"] == ["ZnO-xNiO gas sensors"]
    assert normalized["processes"][0]["evidence"] == ["fabricated"]
    assert normalized["experiments"][0]["evidence"] == ["CO response"]
    with pytest.raises(ValidationError) as caught:
        parse_extracted_document_json(json.dumps(malformed_payload()))
    locations = {tuple(item["loc"]) for item in caught.value.errors()}
    assert ("processes", 0, "name") in locations
    assert ("experiments", 0, "experiment_type") in locations
    unknown = repaired_payload()
    unknown["materials"][0]["invented_scientific_field"] = "not allowed"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_extracted_document_json(json.dumps(unknown))


def test_missing_required_process_and_experiment_fields_trigger_one_model_repair():
    extractor = _extractor([json.dumps(malformed_payload()), json.dumps(repaired_payload())])
    archive = extractor.extract_text(GAS_TEXT, "gas_sensing", source_bundle=_bundle())
    calls = extractor.client.models.calls
    assert len(calls) == 2
    assert "VALIDATION ERRORS" in calls[1]["contents"]
    assert "experiment_type" in calls[1]["contents"] and "processes" in calls[1]["contents"]
    assert archive.metadata.domain == "gas_sensing"
    assert archive.processes[0].name == "fabrication"
    assert archive.experiments[0].experiment_type == "chemiresistive gas sensing"


def test_unrepaired_invalid_document_fails_cleanly_and_admits_no_archive():
    extractor = _extractor([json.dumps(malformed_payload()), json.dumps(malformed_payload())])
    with pytest.raises(StructuredExtractionValidationError) as caught:
        extractor.extract_text(GAS_TEXT, "gas_sensing", source_bundle=_bundle())
    error = caught.value
    assert str(error) == "Structured extraction could not be validated. No invalid scientific records were admitted."
    assert error.route == "gas_sensing" and error.source_id == "src-gas"
    assert error.validation_errors
    assert "Gas-sensing fixture" not in str(error)
    assert len(extractor.client.models.calls) == 2


def test_allowlisted_bundle_metadata_and_nested_condition_evidence_are_normalized_exactly():
    document = parse_extracted_document_json(json.dumps(condition_payload()), source_bundle=_bundle())
    assert document.source.model_dump() == {"title": "Gas-sensing fixture", "doi": None, "url": None, "year": None, "authors": []}
    conditions = document.experiments[0].conditions
    assert [item.value for item in conditions] == [500, 5]
    for condition in conditions:
        evidence = condition.evidence[0]
        assert evidence.source_id == "src-gas"
        assert evidence.page == 1
        assert evidence.source_type.value == "text"
        assert evidence.original_source_type == "native_text"
        assert evidence.verbatim_match is True

    unknown = condition_payload()
    unknown["source"]["invented_scientific_field"] = "must remain invalid"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_extracted_document_json(json.dumps(unknown), source_bundle=_bundle())

    unsupported = condition_payload()
    unsupported["experiments"][0]["conditions"][0]["evidence"] = ["not present in the authoritative source"]
    with pytest.raises(ValidationError):
        parse_extracted_document_json(json.dumps(unsupported), source_bundle=_bundle())


def test_repair_contract_forbids_transport_fields_and_pipeline_reattaches_authoritative_provenance(monkeypatch):
    invalid = condition_payload()
    invalid["processes"][0].pop("name", None)
    repaired = condition_payload()

    class OfflineRecoveryExtractor(DomainGeminiExtractor):
        model_calls = []

        def __init__(self, **kwargs):
            self.registry = __import__("synthex_platform.core.registry", fromlist=["DomainRegistry"]).DomainRegistry()
            self.model = "offline-fake"
            self.client = SimpleNamespace(models=type("Models", (), {
                "generate_content": lambda models, **kwargs: (
                    OfflineRecoveryExtractor.model_calls.append(kwargs) or SimpleNamespace(
                        text=json.dumps(invalid if len(OfflineRecoveryExtractor.model_calls) == 1 else repaired)
                    )
                ),
            })())

    import synthex_platform.extraction.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "DomainGeminiExtractor", OfflineRecoveryExtractor)
    route, archive = SynthexExtractionPipeline().extract_source_bundle(_bundle(), domain="gas_sensing")
    assert route.domain == "gas_sensing"
    assert len(OfflineRecoveryExtractor.model_calls) == 2
    repair_prompt = OfflineRecoveryExtractor.model_calls[1]["contents"]
    assert "Never put source_id, filename, or source_checksum" in repair_prompt
    assert "nested experiment conditions" in repair_prompt
    assert archive.sources[0].checksum == "gas-checksum"
    assert archive.domain_payloads[0].values["source_context"]["source_id"] == "src-gas"
    assert archive.experiments[0].conditions[0].evidence[0].source_id == "src-gas"
    provider_payload = next(item for item in archive.domain_payloads if item.domain == "llm_provider")
    assert provider_payload.values["requested_model"] == "offline-fake"
    assert provider_payload.values["actual_model"] == "offline-fake"
    assert [item["phase"] for item in provider_payload.values["attempts"]] == ["primary", "schema_repair"]


def test_gas_sensing_routes_to_generic_manifest_extractor_and_pipeline_preserves_typed_failure(monkeypatch):
    route = DomainRouter().route_text(GAS_TEXT)
    assert route.domain == "gas_sensing"

    import synthex_platform.extraction.pipeline as pipeline_module

    class FailingGenericExtractor:
        model = "offline-fake"

        def __init__(self, **kwargs):
            pass

        def extract_text(self, text, domain, source_bundle=None):
            assert domain == "gas_sensing"
            raise StructuredExtractionValidationError(
                route=domain, source_id="src-gas", validation_errors=[{"msg": "missing"}], raw_output="very large output",
            )

    monkeypatch.setattr(pipeline_module, "DomainGeminiExtractor", FailingGenericExtractor)
    with pytest.raises(StructuredExtractionValidationError, match="could not be validated"):
        SynthexExtractionPipeline().extract_text(GAS_TEXT, domain="gas_sensing")
