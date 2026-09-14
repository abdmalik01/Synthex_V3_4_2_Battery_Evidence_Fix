from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from synthex_platform.extraction.catalysis_assembler import assemble_catalysis_archive
from synthex_platform.extraction.catalysis_candidate_inventory import (
    CatalysisCandidateCoverage,
    CatalysisCoverageDisposition,
    CatalysisCoverageRecoverer,
    CatalysisCoverageResponse,
    CatalysisQuantitativeCandidate,
    build_catalysis_candidate_inventory,
    compare_catalysis_candidate_coverage,
    merge_catalysis_coverage_response,
)
from synthex_platform.extraction.catalysis_models import (
    CatalysisDocument,
    CatalysisEvidence,
    CatalysisQuantity,
    CatalystMaterial,
    HeterogeneousCatalysisExperiment,
    HeterogeneousMetric,
    ReactionDefinition,
    ReactionSpecies,
    StabilityTest,
)
from synthex_platform.extraction.catalysis_evidence import verify_catalysis_evidence
from synthex_platform.extraction.source_context import (
    SourceBundle,
    SourceMetadata,
    SourcePageContext,
)
import synthex_platform.extraction.pipeline as pipeline_module
from synthex_platform.core.registry import DomainRegistry


SID = "src-candidate-test"
CHECKSUM = "a" * 64


def _bundle(*pages: tuple[str, str, str]) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(source_id=SID, filename="fixture.pdf", source_checksum=CHECKSUM),
        pages=[
            SourcePageContext(
                page=index,
                native_text=native,
                text=effective,
                native_parser="pypdf" if native else "none",
                parser="ocr" if origin == "ocr_extracted" else "pypdf",
                origin=origin,
                sufficient=True,
            )
            for index, (native, effective, origin) in enumerate(pages, start=1)
        ],
    )


def _candidate(snippet: str, numbers: list[str], page: int = 1) -> CatalysisQuantitativeCandidate:
    return CatalysisQuantitativeCandidate(
        candidate_id=f"catcand-{page}", source_id=SID, source_checksum=CHECKSUM,
        page=page, snippet=snippet, numeric_spans=numbers, unit_spans=["%", "°C"],
        lexical_cues=["conversion"], origin="native_text", ranking_score=7, priority="high",
    )


def _evidence(snippet: str, page: int = 1) -> CatalysisEvidence:
    return CatalysisEvidence(
        source_id=SID, page=page, text_snippet=snippet, source_type="text",
        original_source_type="native_text", verbatim_match=True,
    )


def _reaction() -> ReactionDefinition:
    return ReactionDefinition(
        reported_reaction="CO2 methanation", reaction_class="hydrogenation",
        reactants=[ReactionSpecies(reported_name="CO2")],
        products=[ReactionSpecies(reported_name="CH4")],
    )


def _document(
    *, snippet: str | None = None, value: str = "~80", catalyst_evidence: bool = False,
) -> CatalysisDocument:
    evidence = [_evidence(snippet)] if snippet else []
    return CatalysisDocument(
        catalysts=[CatalystMaterial(
            local_id="co", reported_name="MMONiCo", ownership="focal_work",
            evidence=evidence if catalyst_evidence else [],
        )],
        heterogeneous_experiments=[HeterogeneousCatalysisExperiment(
            experiment_id="exp-co", catalyst_ref="co", reaction=_reaction(),
            temperature=CatalysisQuantity(raw_value="350 °C", value=350, unit="°C", qualifier="exact"),
            metrics=[HeterogeneousMetric(
                property="conversion", raw_value=value, value=float(value.lstrip("~")), unit="%",
                qualifier="approx" if value.startswith("~") else "exact", reactant="CO2",
                ownership="focal_work", evidence=evidence,
            )],
            ownership="focal_work", evidence=evidence,
        )],
    )


def test_inventory_detects_one_value_approximation_and_temperature():
    text = "Catalytic CO2 conversion was approximately 81.5 % at 325 °C."
    items = build_catalysis_candidate_inventory(_bundle((text, text, "native_text")))
    assert len(items) == 1
    assert items[0].numeric_spans == ["approximately 81.5", "325"]
    assert items[0].priority == "high"
    assert items[0].origin == "native_text"


def test_inventory_keeps_comparative_two_value_context_in_one_block():
    text = (
        "Fig. 9B shows catalytic methanation using MMONiCo and MMONiFe. "
        "The material containing Co experienced better CO2 conversions (~80 % at 350 °C) "
        "than that containing Fe (50 % at 350 °C)."
    )
    items = build_catalysis_candidate_inventory(_bundle((text, text, "native_text")))
    assert len(items) == 1
    assert "MMONiCo and MMONiFe" in items[0].snippet
    assert items[0].numeric_spans == ["~80", "350", "50", "350"]
    assert "9" not in items[0].numeric_spans


def test_inventory_handles_multiple_catalysts_and_repeated_numbers_on_distinct_pages():
    first = "Catalyst A conversion was 50 % at 300 °C."
    second = "Catalyst B conversion was 50 % at 350 °C."
    items = build_catalysis_candidate_inventory(_bundle(
        (first, first, "native_text"), (second, second, "native_text"),
    ))
    assert {item.page for item in items} == {1, 2}
    assert len({item.candidate_id for item in items}) == 2
    assert [item.candidate_id for item in build_catalysis_candidate_inventory(_bundle(
        (first, first, "native_text"), (second, second, "native_text"),
    ))] == [item.candidate_id for item in items]


def test_inventory_excludes_non_catalytic_quantitative_prose_and_lowers_background():
    text = (
        "The specimen was heated to 500 °C for microscopy. "
        "Previous studies reported CO2 conversion of 90 % at 300 °C."
    )
    items = build_catalysis_candidate_inventory(_bundle((text, text, "native_text")))
    assert len(items) == 1
    assert items[0].priority == "low"
    assert "microscopy" not in items[0].snippet


def test_inventory_prefers_accepted_native_text_and_uses_ocr_only_for_ocr_page():
    native = "Native CO2 conversion was 70 % at 300 °C."
    stale = "OCR CO2 conversion was 99 % at 999 °C."
    ocr = "OCR CO2 conversion was 65 % at 280 °C."
    items = build_catalysis_candidate_inventory(_bundle(
        (native, stale, "native_text"), ("", ocr, "ocr_extracted"),
    ))
    assert any(item.origin == "native_text" and "70" in item.snippet for item in items)
    assert any(item.origin == "ocr_extracted" and "65" in item.snippet for item in items)
    assert all("999" not in item.snippet for item in items)


def test_coverage_requires_same_page_contextual_evidence_and_all_comparative_values():
    snippet = "MMONiCo converted ~80 % at 350 °C whereas MMONiFe converted 50 % at 350 °C."
    candidate = _candidate(snippet, ["~80", "350", "50", "350"])
    partial = compare_catalysis_candidate_coverage(_document(snippet=snippet), [candidate])[0]
    assert not partial.covered
    assert partial.missing_numeric_spans == ["50"]

    wrong_page_doc = _document(snippet=snippet)
    wrong_page_doc.heterogeneous_experiments[0].metrics[0].evidence[0].page = 2
    wrong_page_doc.heterogeneous_experiments[0].evidence[0].page = 2
    wrong = compare_catalysis_candidate_coverage(wrong_page_doc, [candidate])[0]
    assert not wrong.covered
    assert wrong.reason == "no_contextual_evidence_match"


def test_coverage_marks_exact_evidence_overlap_with_all_numbers_covered():
    snippet = "MMONiCo CO2 conversion was ~80 % at 350 °C."
    candidate = _candidate(snippet, ["~80", "350"])
    result = compare_catalysis_candidate_coverage(_document(snippet=snippet), [candidate])[0]
    assert result.covered
    assert result.reason == "evidence_linked_all_numeric_spans"


class _Response:
    def __init__(self, text: str):
        self.text = text


class _Models:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        return _Response(self.outputs.pop(0))


class _Client:
    def __init__(self, outputs: list[str]):
        self.models = _Models(outputs)


def test_recoverer_is_one_call_strict_and_does_not_repair_malformed_response():
    client = _Client(["[]", json.dumps({"dispositions": []})])
    recoverer = CatalysisCoverageRecoverer(client=client, model="offline")
    with pytest.raises(ValueError, match="top-level JSON object"):
        recoverer.recover(CatalysisDocument(), [_candidate("CO2 conversion was 50 %.", ["50"])])
    assert client.models.calls == 1


def _accepted_response(candidate, *, value: str = "50", experiment_id: str = "exp-fe"):
    evidence = [_evidence(candidate.snippet, candidate.page)]
    return CatalysisCoverageResponse(dispositions=[CatalysisCoverageDisposition(
        candidate_id=candidate.candidate_id, status="accepted", reason="explicit focal prose",
        catalysts=[CatalystMaterial(
            local_id="co", reported_name="MMONiCo", ownership="focal_work", evidence=evidence,
        )],
        heterogeneous_experiments=[HeterogeneousCatalysisExperiment(
            experiment_id=experiment_id, catalyst_ref="co", reaction=_reaction(),
            temperature=CatalysisQuantity(raw_value="350 °C", value=350, unit="°C", qualifier="exact"),
            metrics=[HeterogeneousMetric(
                property="conversion", raw_value=value, value=float(value), unit="%", qualifier="exact",
                reactant="CO2", ownership="focal_work", evidence=evidence,
            )],
            ownership="focal_work", evidence=evidence,
        )],
    )])


def test_response_schema_rejects_malformed_and_rejected_additions():
    with pytest.raises(ValidationError):
        CatalysisCoverageResponse.model_validate({"dispositions": [{"candidate_id": "x"}]})
    with pytest.raises(ValidationError):
        CatalysisCoverageDisposition(
            candidate_id="x", status="rejected", reason="background",
            catalysts=[CatalystMaterial(local_id="x")],
        )


def test_safe_merge_adds_supported_values_and_normal_admission_still_applies():
    snippet = "MMONiCo CO2 conversion was 50 % at 350 °C."
    candidate = _candidate(snippet, ["50", "350"])
    primary = _document()
    primary.heterogeneous_experiments = []
    merged, audit = merge_catalysis_coverage_response(primary, _accepted_response(candidate), [candidate])
    assert audit["accepted_candidates"] == 1
    assert len(merged.heterogeneous_experiments) == 1
    archive = assemble_catalysis_archive(merged, source_bundle=_bundle((snippet, snippet, "native_text")))
    assert len(archive.materials) == 1
    assert len(archive.experiments) == 1
    assert archive.experiments[0].outputs[0].property == "conversion"


def test_safe_merge_rejects_unsupported_candidate_evidence_without_guessing():
    snippet = "MMONiCo CO2 conversion was 50 % at 350 °C."
    candidate = _candidate(snippet, ["50", "350"])
    response = _accepted_response(candidate)
    response.dispositions[0].heterogeneous_experiments[0].metrics[0].evidence[0].text_snippet = "not in source"
    merged, audit = merge_catalysis_coverage_response(CatalysisDocument(), response, [candidate])
    assert audit["accepted_candidates"] == 0
    assert not merged.heterogeneous_experiments


def test_safe_merge_suppresses_duplicate_and_preserves_conflict():
    snippet = "MMONiCo CO2 conversion was 80 % at 350 °C and a second report gave 50 %."
    primary = _document(snippet=snippet, value="80", catalyst_evidence=True)
    duplicate_candidate = _candidate(snippet, ["80", "350"])
    duplicate, audit = merge_catalysis_coverage_response(
        primary, _accepted_response(duplicate_candidate, value="80", experiment_id="exp-co"), [duplicate_candidate],
    )
    assert len(duplicate.heterogeneous_experiments[0].metrics) == 1
    assert audit["duplicate_additions"] == 1

    candidate = _candidate(snippet, ["80", "350", "50"])
    conflicted, audit = merge_catalysis_coverage_response(
        primary, _accepted_response(candidate, value="50", experiment_id="exp-co"), [candidate],
    )
    assert len(conflicted.heterogeneous_experiments[0].metrics) == 1
    assert len(conflicted.condition_conflicts) == 1
    assert audit["conflicts_preserved"] == 1


def test_same_number_on_wrong_snippet_is_not_coverage():
    candidate = _candidate("Target catalyst conversion was 50 % at 350 °C.", ["50", "350"])
    document = _document(snippet="Another catalyst conversion was 50 % at 350 °C.", value="50")
    result: CatalysisCandidateCoverage = compare_catalysis_candidate_coverage(document, [candidate])[0]
    assert not result.covered


def test_pipeline_runs_one_batched_coverage_call_and_then_normal_assembly(monkeypatch):
    snippet = "MMONiCo CO2 conversion was 50 % at 350 °C."

    class FakeExtractor:
        model = "offline-primary"
        registry = DomainRegistry()
        client = object()
        last_diagnostics = {
            "gemini_calls": 1, "repair_calls": 0, "schema_valid_first_response": True,
            "schema_valid_repaired_response": False, "persistent_failure": False,
        }
        last_raw_output = "{}"
        last_repaired_output = None

        def __init__(self, **_kwargs):
            pass

        def extract_text(self, *_args, **_kwargs):
            return CatalysisDocument(catalysts=[CatalystMaterial(
                local_id="co", reported_name="MMONiCo", ownership="focal_work",
            )])

    class FakeRecoverer:
        calls = 0

        def __init__(self, **_kwargs):
            self.last_raw_output = None

        def recover(self, _document, candidates):
            type(self).calls += 1
            candidate = next(item for item in candidates if "50 %" in item.snippet)
            response = _accepted_response(candidate)
            self.last_raw_output = response.model_dump_json()
            return response

    monkeypatch.setattr(pipeline_module, "CatalysisGeminiExtractor", FakeExtractor)
    monkeypatch.setattr(pipeline_module, "CatalysisCoverageRecoverer", FakeRecoverer)
    pipeline = pipeline_module.SynthexExtractionPipeline()
    _, archive = pipeline.extract_source_bundle(_bundle((snippet, snippet, "native_text")), domain="catalysis")
    assert FakeRecoverer.calls == 1
    assert pipeline.last_extraction_diagnostics["primary_calls"] == 1
    assert pipeline.last_extraction_diagnostics["schema_repair_calls"] == 0
    assert pipeline.last_extraction_diagnostics["coverage_calls"] == 1
    assert pipeline.last_extraction_diagnostics["gemini_calls"] == 2
    assert len(archive.experiments) == 1
    assert archive.experiments[0].outputs[0].raw_value == "50"


def test_pipeline_coverage_failure_is_graceful_and_never_retries(monkeypatch):
    snippet = "MMONiCo CO2 conversion was 50 % at 350 °C."

    class FakeExtractor:
        model = "offline-primary"
        registry = DomainRegistry()
        client = object()
        last_diagnostics = {
            "gemini_calls": 1, "repair_calls": 0, "schema_valid_first_response": True,
            "schema_valid_repaired_response": False, "persistent_failure": False,
        }
        last_raw_output = "{}"
        last_repaired_output = None

        def __init__(self, **_kwargs):
            pass

        def extract_text(self, *_args, **_kwargs):
            return CatalysisDocument()

    class FailingRecoverer:
        calls = 0

        def __init__(self, **_kwargs):
            self.last_raw_output = "[]"

        def recover(self, *_args):
            type(self).calls += 1
            raise ValueError("malformed coverage response")

    monkeypatch.setattr(pipeline_module, "CatalysisGeminiExtractor", FakeExtractor)
    monkeypatch.setattr(pipeline_module, "CatalysisCoverageRecoverer", FailingRecoverer)
    pipeline = pipeline_module.SynthexExtractionPipeline()
    _, archive = pipeline.extract_source_bundle(_bundle((snippet, snippet, "native_text")), domain="catalysis")
    assert FailingRecoverer.calls == 1
    assert pipeline.last_extraction_diagnostics["coverage_calls"] == 1
    assert "malformed coverage response" in pipeline.last_extraction_diagnostics["coverage_validation_error"]
    assert archive.experiments == []


def test_catalysis_native_evidence_tolerates_only_parser_nul_separator():
    source = "MMONiCo (150 mol CH4 h\x001 L\x001)"
    evidence = CatalysisEvidence(
        source_id=SID, page=1, text_snippet="MMONiCo (150 mol CH4 h 1 L 1)",
        source_type="text", original_source_type="native_text",
    )
    assert verify_catalysis_evidence(
        evidence, source_bundle=_bundle((source, source, "native_text")),
    )
    assert evidence.evidence_strength == "verified_native"


def test_stability_can_resolve_material_through_valid_parent_reference_without_parent_output():
    sty_snippet = "MMONiCo + Ce productivity was 168 mol CH4 h 1 L 1 at 350 °C."
    stability_snippet = "MMONiCo + Ce retained ~85 % CO2 conversion after 1400 min."
    evidence_sty = [_evidence(sty_snippet)]
    evidence_stability = [_evidence(stability_snippet)]
    document = CatalysisDocument(
        catalysts=[CatalystMaterial(
            local_id="co-ce", reported_name="MMONiCo + Ce", ownership="focal_work",
        )],
        heterogeneous_experiments=[HeterogeneousCatalysisExperiment(
            experiment_id="parent", catalyst_ref="co-ce", reaction=_reaction(),
            metrics=[HeterogeneousMetric(
                property="productivity", raw_value="168", value=168,
                unit="mol CH4 h-1 L-1", product="CH4", ownership="focal_work",
                evidence=evidence_sty,
            )],
            ownership="focal_work", evidence=evidence_sty,
        )],
        stability_tests=[StabilityTest(
            stability_id="stable", experiment_ref="parent", mode="time_on_stream",
            duration=CatalysisQuantity(raw_value="1400 min", value=1400, unit="min", qualifier="exact"),
            retained_metric=HeterogeneousMetric(
                property="conversion", raw_value="~85 %", value=85, unit="%", qualifier="approx",
                reactant="CO2", ownership="focal_work", evidence=evidence_stability,
            ),
            ownership="focal_work", evidence=evidence_stability,
        )],
    )
    source = f"{sty_snippet} {stability_snippet}"
    archive = assemble_catalysis_archive(
        document, source_bundle=_bundle((source, source, "native_text")),
    )
    assert len(archive.materials) == 1
    assert len(archive.experiments) == 1
    assert archive.experiments[0].experiment_type == "catalyst_stability"
    assert archive.experiments[0].outputs[0].raw_value == "~85 %"
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    assert any(item["reason"] == "normalization_basis_unknown" for item in audit["quarantine"])
