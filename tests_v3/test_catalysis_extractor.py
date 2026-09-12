from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.catalysis_extractor import CatalysisGeminiExtractor, parse_catalysis_document_json
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.visual.models import FigureRecord, VisualProvenance


def _payload():
    return {
        "source": {"title": "Catalysis fixture"},
        "paper_types": ["electrocatalysis"],
        "electrocatalysis_experiments": [{
            "experiment_id": "ec-1",
            "reaction": {"reaction_class": "her", "reported_reaction": "HER"},
            "metrics": [{
                "property": "overpotential", "raw_value": "280 mV", "value": 280, "unit": "mV",
                "potential": {"raw_potential": {"raw_value": "1.51 V vs RHE", "value": 1.51, "unit": "V"}, "reported_reference": "RHE"},
            }],
        }],
    }


def _bundle():
    figure = FigureRecord(
        figure_id="fig-cat", source_id="src-cat", page=2, caption="Fig. 2. HER polarization curve.",
        figure_type="polarization",
        provenance=VisualProvenance(origin="figure_caption", source_id="src-cat", page=2, object_id="fig-cat", object_type="figure"),
    )
    return SourceBundle(
        source=SourceMetadata(source_id="src-cat", filename="cat.pdf", source_checksum="abc"),
        pages=[SourcePageContext(page=1, native_text="HER was tested.", text="HER was tested.", native_parser="pypdf", parser="pypdf", sufficient=True, attempt_history=["pypdf"])],
        figures=[figure],
    )


def test_strict_catalysis_json_parser_accepts_object_and_singleton_only():
    assert parse_catalysis_document_json(json.dumps(_payload())).source.title == "Catalysis fixture"
    assert parse_catalysis_document_json(json.dumps([_payload()])).paper_types == ["electrocatalysis"]
    with pytest.raises(ValueError, match="empty JSON array"):
        parse_catalysis_document_json("[]")
    with pytest.raises(ValueError, match="refusing to merge"):
        parse_catalysis_document_json(json.dumps([_payload(), _payload()]))
    with pytest.raises(ValueError, match="top-level JSON str"):
        parse_catalysis_document_json(json.dumps("bad"))


def test_prompt_supports_text_only_and_bounded_source_bundle_context():
    extractor = CatalysisGeminiExtractor.__new__(CatalysisGeminiExtractor)
    extractor.registry = DomainRegistry()
    text_only = extractor.build_prompt("plain catalysis source")
    contextual = extractor.build_prompt("--- PAGE 1 ---\nHER was tested.", source_bundle=_bundle())
    assert "STRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):" not in text_only
    assert "STRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):" in contextual
    assert "fig-cat" in contextual
    assert "Digitized graph references are estimated" in contextual


def test_extractor_uses_local_validation_and_stage1_warnings_without_live_api():
    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["config"]["response_mime_type"] == "application/json"
            return SimpleNamespace(text=json.dumps(_payload()))

    extractor = CatalysisGeminiExtractor.__new__(CatalysisGeminiExtractor)
    extractor.registry = DomainRegistry()
    extractor.model = "offline-fake"
    extractor.client = SimpleNamespace(models=FakeModels())
    result = extractor.extract_text("HER source", source_bundle=_bundle())
    assert result.electrocatalysis_experiments[0].metrics[0].property == "overpotential"
