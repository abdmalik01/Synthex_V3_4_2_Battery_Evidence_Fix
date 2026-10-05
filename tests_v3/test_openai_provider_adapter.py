from __future__ import annotations

import json

import pytest

from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder
from synthex_platform.benchmarks.provider_retry import run_provider_with_retries
from synthex_platform.extraction.domain_extractor import DomainProviderExtractor
from synthex_platform.providers import (
    GeminiAdapter,
    OpenAIAdapter,
    ProviderAdapter,
    ProviderErrorClass,
    ProviderRequest,
)


VALID_DOCUMENT = json.dumps({
    "source": {"title": "fixture"},
    "materials": [], "devices": [], "processes": [],
    "experiments": [], "calculations": [],
    "domain_values": {}, "extraction_notes": [],
})


class Usage:
    input_tokens = 11
    output_tokens = 7
    total_tokens = 18
    input_tokens_details = type("InputDetails", (), {"cached_tokens": 3})()


class OpenAIResponse:
    def __init__(self, text=VALID_DOCUMENT, model="gpt-exact-provider-version"):
        self.output_text = text
        self.model = model
        self.status = "completed"
        self.usage = Usage()

    def model_dump(self):
        return {"output_text": self.output_text, "model": self.model}


class Responses:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [OpenAIResponse()])
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _adapter(outcomes=None, model_id="gpt-configured-exact"):
    responses = Responses(outcomes)
    client = type("Client", (), {"responses": responses})()
    return OpenAIAdapter(client=client, model_id=model_id, mode="benchmark"), responses


def test_openai_adapter_satisfies_common_contract_and_exact_identity():
    adapter, _ = _adapter()
    assert isinstance(adapter, ProviderAdapter)
    response = adapter.generate_candidate(ProviderRequest("fixture"))
    assert response.identity.provider_name == "openai"
    assert response.identity.model_id == "gpt-configured-exact"
    assert response.identity.configured_model_id == "gpt-configured-exact"
    assert response.identity.provider_reported_model_id == "gpt-exact-provider-version"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.total_tokens == 18
    assert response.usage.cached_tokens == 3
    assert response.latency_ms >= 0


def test_openai_native_json_schema_and_json_mode_translation():
    adapter, responses = _adapter([OpenAIResponse(), OpenAIResponse()])
    schema = {"type": "object", "properties": {"value": {"type": "number"}}, "required": ["value"], "additionalProperties": False}
    adapter.generate_candidate(ProviderRequest(
        "fixture", response_mime_type="application/json",
        response_schema=schema, response_schema_name="fixture_schema",
    ))
    adapter.generate_candidate(ProviderRequest("fixture", response_mime_type="application/json"))
    assert responses.calls[0]["text"]["format"] == {
        "type": "json_schema", "name": "fixture_schema", "strict": True, "schema": schema,
    }
    assert responses.calls[1]["text"]["format"] == {"type": "json_object"}
    assert all(call["store"] is False for call in responses.calls)


def test_openai_primary_and_repair_are_separate_and_exact_model_pinned(tmp_path):
    adapter, responses = _adapter([OpenAIResponse("primary"), OpenAIResponse("repair")])
    recorder = ProviderArtifactRecorder(
        tmp_path / "attempt", provider="openai", model="gpt-configured-exact", attempt=1,
    )
    primary = adapter.generate_candidate(ProviderRequest("x", phase="primary"))
    recorder("raw_response", primary.text)
    repair = adapter.repair_candidate(ProviderRequest("y", phase="schema_repair"))
    recorder("repair_request", "y")
    recorder("repair_response", repair.text)
    assert (tmp_path / "attempt/raw_response.txt").read_text(encoding="utf-8") == "primary"
    assert (tmp_path / "attempt/repair_response.txt").read_text(encoding="utf-8") == "repair"
    assert [call["model"] for call in responses.calls] == ["gpt-configured-exact"] * 2
    assert adapter.audit()["fallback_occurred"] is False


class NativeError(RuntimeError):
    def __init__(self, message, status_code, request_id="req-safe"):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.code = "native_code"


@pytest.mark.parametrize(("status", "message", "expected"), [
    (503, "service unavailable", ProviderErrorClass.TRANSIENT_UNAVAILABLE),
    (429, "rate limit", ProviderErrorClass.RATE_LIMITED),
    (401, "authentication failed", ProviderErrorClass.AUTHENTICATION_FAILED),
    (400, "invalid request", ProviderErrorClass.INVALID_REQUEST),
    (413, "context length exceeded", ProviderErrorClass.CONTEXT_TOO_LARGE),
])
def test_openai_error_normalization_preserves_safe_native_diagnostics(status, message, expected):
    adapter, _ = _adapter()
    normalized = adapter.classify_error(NativeError(message, status))
    assert normalized.error_class is expected
    assert normalized.raw_diagnostic["status_code"] == status
    assert normalized.raw_diagnostic["request_id"] == "req-safe"


def test_openai_error_diagnostics_redact_credentials():
    adapter, _ = _adapter()
    normalized = adapter.classify_error(
        NativeError("503 Authorization: Bearer top-secret api_key=sk-secret", 503)
    )
    persisted = json.dumps(normalized.raw_diagnostic)
    assert "top-secret" not in persisted
    assert "sk-secret" not in persisted
    assert "[REDACTED]" in persisted


def test_openai_transient_retry_and_unavailable_is_not_scientific_zero(tmp_path):
    adapter, _ = _adapter([
        NativeError("503 unavailable", 503), NativeError("503 unavailable", 503),
    ])
    result, ledger = run_provider_with_retries(
        lambda: adapter.generate_candidate(ProviderRequest("x")),
        provider="openai", model_id="gpt-configured-exact", run_id="run",
        ledger_path=tmp_path / "ledger.json", adapter=adapter,
        max_attempts=2, wait=lambda _: None,
    )
    assert result is None
    assert ledger["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES"
    assert all(not attempt["payload_returned"] for attempt in ledger["attempts"])
    assert "scientific_score" not in ledger


def test_schema_invalid_openai_payload_is_persisted_before_validation(tmp_path):
    adapter, _ = _adapter([OpenAIResponse("not-json"), OpenAIResponse("not-json")])
    recorder = ProviderArtifactRecorder(
        tmp_path / "attempt", provider="openai", model="gpt-configured-exact", attempt=1,
    )
    extractor = DomainProviderExtractor(provider_adapter=adapter, artifact_sink=recorder)
    with pytest.raises(Exception, match="validated|validation"):
        extractor.extract_text("fixture", "generic")
    assert (tmp_path / "attempt/raw_response.txt").read_text(encoding="utf-8") == "not-json"
    assert (tmp_path / "attempt/raw_validation_report.json").exists()
    assert (tmp_path / "attempt/repair_response.txt").read_text(encoding="utf-8") == "not-json"


def test_cross_provider_candidate_semantics_and_admission_are_identical():
    class GeminiResponse:
        text = VALID_DOCUMENT
        model_version = "gemini-provider-version"
        usage_metadata = None

        @staticmethod
        def model_dump():
            return {"text": VALID_DOCUMENT}

    class Models:
        @staticmethod
        def generate_content(**_kwargs):
            return GeminiResponse()

    gemini = GeminiAdapter(
        client=type("GeminiClient", (), {"models": Models()})(),
        model_id="models/gemini-exact", mode="benchmark",
    )
    openai, _ = _adapter()
    archives = [
        DomainProviderExtractor(provider_adapter=adapter).extract_text("fixture", "generic")
        for adapter in (gemini, openai)
    ]
    comparable = [
        archive.model_dump(mode="json", exclude={"metadata": {"extractor_model", "created_at", "archive_id"}})
        for archive in archives
    ]
    assert comparable[0] == comparable[1]


def test_no_openai_native_object_leaks_into_scientific_archive():
    adapter, _ = _adapter()
    archive = DomainProviderExtractor(provider_adapter=adapter).extract_text("fixture", "generic")
    assert "OpenAIResponse" not in archive.model_dump_json()
