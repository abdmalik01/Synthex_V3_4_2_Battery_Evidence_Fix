from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from synthex_platform.extraction.corrosion_extractor import (
    MAX_CORROSION_REPAIR_ATTEMPTS,
    CorrosionGeminiExtractor,
    CorrosionStructuredExtractionValidationError,
    corrosion_output_contract,
    parse_corrosion_document_json,
)
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.extraction import pipeline as pipeline_module


SOURCE_TEXT = """--- PAGE 1 ---
AA2024-T3 was immersed in 3.5 wt% NaCl. Potentiodynamic polarization was measured versus Ag/AgCl.
The corrosion current density was 2.5 uA/cm2 and the corrosion potential was -0.62 V vs Ag/AgCl.
"""


def _bundle() -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-corrosion-test",
            filename="corrosion.pdf",
            source_checksum="corrosion-checksum",
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


def _payload() -> dict:
    material_ev = [{
        "source_id": "src-corrosion-test",
        "page": 1,
        "text_snippet": "AA2024-T3 was immersed in 3.5 wt% NaCl.",
        "source_type": "text",
        "original_source_type": "native_text",
        "verbatim_match": True,
    }]
    experiment_ev = [{
        "source_id": "src-corrosion-test",
        "page": 1,
        "text_snippet": "Potentiodynamic polarization was measured versus Ag/AgCl.",
        "source_type": "text",
        "original_source_type": "native_text",
        "verbatim_match": True,
    }]
    metric_ev = [{
        "source_id": "src-corrosion-test",
        "page": 1,
        "text_snippet": "The corrosion current density was 2.5 uA/cm2 and the corrosion potential was -0.62 V vs Ag/AgCl.",
        "source_type": "text",
        "original_source_type": "native_text",
        "verbatim_match": True,
    }]
    return {
        "source": {"title": "AA2024 corrosion study"},
        "paper_types": ["polarization_corrosion"],
        "scope_status": "supported",
        "materials": [{
            "local_id": "mat_aa2024",
            "reported_name": "AA2024-T3",
            "material_class": "alloy",
            "role": "corroding_material",
            "ownership": "focal_work",
            "evidence": material_ev,
        }],
        "environments": [{
            "environment_id": "env_nacl",
            "medium": "3.5 wt% NaCl",
            "evidence": material_ev,
        }],
        "experiments": [{
            "experiment_id": "exp_pol",
            "experiment_type": "potentiodynamic_polarization",
            "material_refs": ["mat_aa2024"],
            "environment_ref": "env_nacl",
            "polarization_conditions": {
                "reference_electrode": "Ag/AgCl",
                "evidence": experiment_ev,
            },
            "metrics": [
                {
                    "property": "corrosion_current_density",
                    "quantity": {"raw_value": "2.5 uA/cm2", "value": 2.5, "unit": "uA/cm2", "qualifier": "exact"},
                    "ownership": "focal_work",
                    "evidence": metric_ev,
                },
                {
                    "property": "corrosion_potential",
                    "quantity": {"raw_value": "-0.62 V", "value": -0.62, "unit": "V", "qualifier": "exact"},
                    "ownership": "focal_work",
                    "evidence": metric_ev,
                },
            ],
            "ownership": "focal_work",
            "evidence": experiment_ev,
        }],
    }


def test_corrosion_contract_is_strict_and_single_repair_is_bounded():
    contract = json.dumps(corrosion_output_contract())
    assert '"additionalProperties": false' in contract
    assert '"corrosion_current_density"' in contract
    assert MAX_CORROSION_REPAIR_ATTEMPTS == 1


def test_corrosion_parser_rejects_multi_document_arrays_and_bad_refs():
    valid = _payload()
    assert parse_corrosion_document_json(json.dumps(valid)).experiments
    with pytest.raises(ValueError, match="exactly one"):
        parse_corrosion_document_json(json.dumps([valid, valid]))
    broken = _payload()
    broken["experiments"][0]["material_refs"] = ["missing"]
    with pytest.raises(ValidationError):
        parse_corrosion_document_json(json.dumps(broken))


def test_prompt_contains_scientific_safety_rules_without_provider_call():
    extractor = CorrosionGeminiExtractor.__new__(CorrosionGeminiExtractor)
    extractor.registry = pipeline_module.DomainRouter().registry
    prompt = extractor.build_prompt(SOURCE_TEXT, source_bundle=_bundle())
    assert "Do not convert electrode potentials" in prompt
    assert "Do not derive corrosion rate" in prompt
    assert "EIS fitted parameters" in prompt
    assert "ACTUAL CORROSION PYDANTIC CONTRACT" in prompt


def test_pipeline_uses_dedicated_corrosion_path_offline(monkeypatch):
    document = CorrosionDocument.model_validate(_payload())

    class FakeExtractor:
        model = "offline-corrosion"
        last_diagnostics = {"gemini_calls": 1, "repair_calls": 0}
        last_provider_audit = {}

        def __init__(self, **_kwargs):
            self.model = "offline-corrosion"
            self.last_diagnostics = {"gemini_calls": 1, "repair_calls": 0}
            self.last_provider_audit = {}

        def extract_text(self, text, source_bundle=None):
            assert "corrosion" in text.casefold() or "AA2024" in text
            return document

    monkeypatch.setattr(pipeline_module, "CorrosionGeminiExtractor", FakeExtractor)
    pipeline = pipeline_module.SynthexExtractionPipeline()
    route, archive = pipeline.extract_source_bundle(_bundle(), domain="corrosion")
    assert route.domain == "corrosion"
    assert archive.metadata.domain == "corrosion"
    assert archive.materials
    assert len(archive.experiments) == 1
    assert {m.property for m in archive.experiments[0].outputs} == {
        "corrosion_current_density", "corrosion_potential"
    }
    assert not archive.calculations
    assert pipeline.last_extraction_diagnostics["primary_calls"] == 1


def test_typed_corrosion_failure_is_concise_and_hash_only():
    error = CorrosionStructuredExtractionValidationError(
        route="corrosion",
        source_id="src-corrosion-test",
        validation_errors=[{"msg": "bad"}],
        repair_attempted=True,
        raw_output_reference="0" * 64,
    )
    assert "invalid scientific records" in str(error)
    assert len(error.raw_output_reference) == 64
