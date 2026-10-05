from __future__ import annotations

from dataclasses import asdict
import inspect
import json

import pytest

from benchmark.photovoltaics_v1.recover_gold_a import recover_gold_a
from synthex_platform.benchmarks.provider_artifacts import (
    ProviderArtifactRecorder,
    create_provider_run_root,
    inspect_provider_run,
    iter_complete_provider_reports,
    read_provider_report,
)
from synthex_platform.benchmarks.provider_retry import run_provider_with_retries
from synthex_platform.extraction.domain_extractor import DomainProviderExtractor
from synthex_platform.providers import (
    ProviderCapabilities,
    ProviderErrorClass,
    GeminiAdapter,
    ProviderModelIdentity,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    discover_gemini_models,
    is_general_text_gemini_model,
    normalize_provider_error,
)
from synthex_platform.providers.contracts import utc_now


VALID_DOCUMENT = json.dumps({
    "source": {"title": "fixture"},
    "materials": [], "devices": [], "processes": [],
    "experiments": [], "calculations": [],
    "domain_values": {}, "extraction_notes": [],
})


class FakeAdapter:
    def __init__(self, model_id="model-a", provider_name="fake", outcomes=None):
        self.provider_name = provider_name
        self.mode = "benchmark"
        self.model_id = model_id
        self.outcomes = list(outcomes or [VALID_DOCUMENT])
        self.calls = []
        self.attempts = []
        self.last = None

    def _call(self, request):
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            self.attempts.append({"phase": request.phase, "status": "failed"})
            raise outcome
        response = ProviderResponse(
            text=outcome, raw_payload={"text": outcome},
            identity=self.get_model_identity(), request_timestamp=utc_now(),
            response_timestamp=utc_now(), latency_ms=1.25,
            usage=ProviderUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        )
        self.last = response
        self.attempts.append({"phase": request.phase, "status": "succeeded"})
        return response

    def generate_candidate(self, request):
        return self._call(request)

    def repair_candidate(self, request):
        return self._call(request)

    def classify_error(self, error):
        return normalize_provider_error(error)

    def get_model_identity(self):
        return ProviderModelIdentity(self.provider_name, self.model_id)

    def get_capabilities(self):
        return ProviderCapabilities(structured_output=True)

    def get_usage(self):
        return self.last.usage if self.last else ProviderUsage()

    def get_latency(self):
        return self.last.latency_ms if self.last else None

    def audit(self):
        return {
            "provider_name": self.provider_name,
            "model_identity": asdict(self.get_model_identity()),
            "attempts": list(self.attempts),
            "usage": asdict(self.get_usage()),
            "latency_ms": self.get_latency(),
            "fallback_occurred": False,
        }


def test_provider_identity_retained():
    adapter = FakeAdapter(provider_name="provider-x")
    assert adapter.generate_candidate(ProviderRequest("x")).identity.provider_name == "provider-x"


def test_model_identity_retained():
    adapter = FakeAdapter(model_id="exact-model-id")
    identity = adapter.generate_candidate(ProviderRequest("x")).identity
    assert identity.model_id == "exact-model-id"
    assert identity.configured_model_id == "exact-model-id"


def test_same_provider_supports_multiple_model_ids():
    assert {FakeAdapter(model_id=value).get_model_identity().model_id for value in ("a", "b", "c")} == {"a", "b", "c"}


def test_configured_and_fallback_model_identities_remain_distinct():
    class Response:
        text = VALID_DOCUMENT
        model_version = "provider-version"
        usage_metadata = None

    class Models:
        calls = []

        @classmethod
        def generate_content(cls, *, model, **_kwargs):
            cls.calls.append(model)
            if model == "preferred-model":
                raise RuntimeError("503 unavailable")
            return Response()

    adapter = GeminiAdapter(
        client=type("Client", (), {"models": Models()})(),
        model_id="preferred-model",
        fallback_models=("fallback-model",),
        mode="production",
    )
    identity = adapter.generate_candidate(ProviderRequest("x")).identity
    assert identity.configured_model_id == "preferred-model"
    assert identity.model_id == "fallback-model"
    assert identity.provider_reported_model_id == "provider-version"
    assert adapter.audit()["fallback_occurred"] is True


def test_two_model_runs_cannot_overwrite_artifacts(tmp_path):
    first, _ = create_provider_run_root(tmp_path, case_id="case", provider_name="gemini", model_id="model-a", run_id="run")
    second, _ = create_provider_run_root(tmp_path, case_id="case", provider_name="gemini", model_id="model-b", run_id="run")
    assert first != second


def test_long_model_ids_use_short_collision_resistant_path_components(tmp_path):
    first, _ = create_provider_run_root(
        tmp_path, case_id="case", provider_name="gemini",
        model_id="models/provider-model-with-a-very-long-shared-prefix-alpha", run_id="run-a",
    )
    second, _ = create_provider_run_root(
        tmp_path, case_id="case", provider_name="gemini",
        model_id="models/provider-model-with-a-very-long-shared-prefix-beta", run_id="run-b",
    )
    assert first.parent != second.parent
    assert len(first.parent.name) <= 24
    assert len(second.parent.name) <= 24


def test_duplicate_run_identity_cannot_overwrite_artifacts(tmp_path):
    create_provider_run_root(tmp_path, case_id="case", provider_name="fake", model_id="m", run_id="same")
    with pytest.raises(FileExistsError):
        create_provider_run_root(tmp_path, case_id="case", provider_name="fake", model_id="m", run_id="same")


def test_automatic_run_ids_are_unique(tmp_path):
    first, first_id = create_provider_run_root(tmp_path, case_id="case", provider_name="fake", model_id="m")
    second, second_id = create_provider_run_root(tmp_path, case_id="case", provider_name="fake", model_id="m")
    assert first != second and first_id != second_id


def test_raw_payload_is_persisted_before_failed_validation(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    recorder("raw_response", "not-json")
    recorder("raw_validation_report", {"valid": False})
    assert (tmp_path / "attempt/raw_response.txt").exists()


def test_validation_artifact_cannot_precede_raw_payload(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    with pytest.raises(RuntimeError, match="cannot precede raw_response"):
        recorder("raw_validation_report", {"valid": False})


def test_schema_invalid_payload_remains_auditable(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    recorder("raw_response", "{")
    recorder("raw_validation_report", {"valid": False, "errors": ["invalid"]})
    assert (tmp_path / "attempt/raw_response.txt").read_text(encoding="utf-8") == "{"


def test_repair_response_does_not_replace_primary(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    recorder("raw_response", "primary")
    recorder("repair_response", "repair")
    assert (tmp_path / "attempt/raw_response.txt").read_text(encoding="utf-8") == "primary"
    assert (tmp_path / "attempt/repair_response.txt").read_text(encoding="utf-8") == "repair"


def test_repair_response_is_itself_immutable(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    recorder("raw_response", "primary")
    recorder("repair_response", "repair-one")
    with pytest.raises(RuntimeError, match="Refusing to overwrite immutable"):
        recorder("repair_response", "repair-two")


def test_benchmark_adapter_reports_no_fallback():
    assert FakeAdapter().audit()["fallback_occurred"] is False


def test_unavailable_model_remains_unavailable(tmp_path):
    adapter = FakeAdapter(model_id="m", outcomes=[RuntimeError("503 unavailable")])
    result, ledger = run_provider_with_retries(
        lambda: adapter.generate_candidate(ProviderRequest("x")),
        provider="fake", model_id="m", run_id="r", ledger_path=tmp_path / "ledger.json",
        adapter=adapter, max_attempts=1, wait=lambda _: None,
    )
    assert result is None and ledger["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES"


def test_transient_retry_is_provider_neutral(tmp_path):
    adapter = FakeAdapter(model_id="m", outcomes=[RuntimeError("503 unavailable"), VALID_DOCUMENT])
    def run():
        response = adapter.generate_candidate(ProviderRequest("x"))
        return {"response": response, "provider_audit": adapter.audit()}
    result, ledger = run_provider_with_retries(
        run, provider="fake", model_id="m", run_id="r",
        ledger_path=tmp_path / "ledger.json", adapter=adapter, wait=lambda _: None,
    )
    assert result is not None and len(ledger["attempts"]) == 2


def test_nontransient_errors_are_not_retried(tmp_path):
    adapter = FakeAdapter(model_id="m", outcomes=[RuntimeError("400 invalid argument"), VALID_DOCUMENT])
    with pytest.raises(RuntimeError):
        run_provider_with_retries(
            lambda: adapter.generate_candidate(ProviderRequest("x")),
            provider="fake", model_id="m", run_id="r", ledger_path=tmp_path / "ledger.json",
            adapter=adapter, wait=lambda _: None,
        )
    assert len(adapter.calls) == 1


def test_deterministic_recovery_does_not_depend_on_provider():
    archive, _ = recover_gold_a()
    assert archive.experiments and not hasattr(archive, "provider_adapter")


def test_canonical_admission_does_not_depend_on_provider_identity():
    outputs = []
    for provider in ("provider-a", "provider-b"):
        extractor = DomainProviderExtractor(provider_adapter=FakeAdapter(provider_name=provider))
        archive = extractor.extract_text("fixture", "generic")
        outputs.append((len(archive.materials), len(archive.experiments), archive.domain_payloads[0].domain))
    assert outputs[0] == outputs[1]


def test_historical_gemini_report_remains_readable(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({
        "case_id": "PV-GOLD-A", "requested_model": "historical-model",
        "actual_model": None, "status": "LIVE_UNAVAILABLE_AFTER_RETRIES",
        "provider_attempts": [{"attempt": 1}], "raw_provider_scientific_score": None,
    }), encoding="utf-8")
    report = read_provider_report(path)
    assert report["provider_name"] == "gemini"
    assert report["configured_model_id"] == "historical-model"
    assert report["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES"
    assert report["original_report"]["requested_model"] == "historical-model"


@pytest.mark.parametrize("message,expected", [
    ("503 high demand", ProviderErrorClass.TRANSIENT_UNAVAILABLE),
    ("429 quota", ProviderErrorClass.RATE_LIMITED),
    ("timed out", ProviderErrorClass.TIMEOUT),
    ("invalid API key", ProviderErrorClass.AUTHENTICATION_FAILED),
    ("400 invalid argument", ProviderErrorClass.INVALID_REQUEST),
    ("context length exceeded", ProviderErrorClass.CONTEXT_TOO_LARGE),
    ("safety blocked", ProviderErrorClass.CONTENT_BLOCKED),
])
def test_provider_errors_are_normalized_and_retain_safe_raw_form(message, expected):
    error = normalize_provider_error(RuntimeError(message))
    assert error.error_class is expected
    assert error.raw_diagnostic["safe_message"]


def test_api_secrets_are_not_persisted_in_error_ledger(tmp_path):
    adapter = FakeAdapter(model_id="m", outcomes=[RuntimeError("503 api_key=secret-value")])
    with pytest.raises(RuntimeError):
        run_provider_with_retries(
            lambda: adapter.generate_candidate(ProviderRequest("x")),
            provider="fake", model_id="m", run_id="r", ledger_path=tmp_path / "ledger.json",
            adapter=adapter, max_attempts=1, wait=lambda _: None,
        )
    persisted = (tmp_path / "ledger.json").read_text(encoding="utf-8")
    assert "secret-value" not in persisted
    assert "[REDACTED]" in persisted


def test_request_metadata_redacts_nested_credentials(tmp_path):
    recorder = ProviderArtifactRecorder(tmp_path / "attempt", model="m", attempt=1)
    recorder("request_metadata", {
        "authorization": "Bearer top-secret-token",
        "nested": {"api_key": "AIza012345678901234567890123456789"},
    })
    persisted = (tmp_path / "attempt/request_metadata.json").read_text(encoding="utf-8")
    assert "top-secret-token" not in persisted
    assert "AIza012345678901234567890123456789" not in persisted


def test_fallback_used_is_false_in_benchmark_ledger(tmp_path):
    adapter = FakeAdapter(model_id="m")
    _, ledger = run_provider_with_retries(
        lambda: {"provider_audit": adapter.audit()}, provider="fake", model_id="m",
        run_id="r", ledger_path=tmp_path / "ledger.json", adapter=adapter,
    )
    assert ledger["fallback_used"] is False


def test_run_ids_isolate_provider_model_run_combinations(tmp_path):
    first, _ = create_provider_run_root(tmp_path, case_id="c", provider_name="p", model_id="m", run_id="r1")
    second, _ = create_provider_run_root(tmp_path, case_id="c", provider_name="p", model_id="m", run_id="r2")
    assert first != second


def test_retry_metadata_must_match_adapter_identity(tmp_path):
    adapter = FakeAdapter(model_id="actual")
    with pytest.raises(ValueError, match="exactly match"):
        run_provider_with_retries(
            lambda: {}, provider="fake", model_id="different", run_id="r",
            ledger_path=tmp_path / "ledger.json", adapter=adapter,
        )


def test_capability_metadata_is_unknown_safe():
    capabilities = ProviderCapabilities()
    assert capabilities.pdf_input is None
    assert capabilities.image_input is None
    assert capabilities.native_schema is None
    assert capabilities.tool_use is None


def test_discovery_preserves_exact_ids_without_fabrication():
    class Model:
        name = "models/gemini-exact-runtime-id"
        display_name = "Runtime Model"
        version = "v1"
        supported_actions = ["generateContent"]
        input_token_limit = 123
        output_token_limit = 45

    class Models:
        @staticmethod
        def list():
            return [Model()]

    discovered = discover_gemini_models(type("Client", (), {"models": Models()})())
    assert [item["model_id"] for item in discovered] == ["models/gemini-exact-runtime-id"]


def test_general_text_model_filter_excludes_specialized_and_non_gemini_models():
    base = {"generate_content": True}
    assert is_general_text_gemini_model({**base, "model_id": "models/gemini-3.7-flash"})
    assert not is_general_text_gemini_model({**base, "model_id": "models/gemini-3.8-flash-tts"})
    assert not is_general_text_gemini_model({**base, "model_id": "models/gemma-4-31b-it"})


def test_incomplete_runs_are_marked_and_excluded_from_complete_reports(tmp_path):
    incomplete = tmp_path / "run-incomplete"
    incomplete.mkdir()
    (incomplete / "incomplete_run.json").write_text(
        json.dumps({"reason": "no final report"}), encoding="utf-8",
    )
    complete = tmp_path / "run-complete"
    complete.mkdir()
    (complete / "report.json").write_text("{}", encoding="utf-8")
    assert inspect_provider_run(incomplete)["summary_eligible"] is False
    assert list(iter_complete_provider_reports(tmp_path)) == [complete / "report.json"]


def test_multiple_model_ids_need_no_domain_code_changes():
    for model_id in ("model-a", "model-b"):
        extractor = DomainProviderExtractor(provider_adapter=FakeAdapter(model_id=model_id))
        assert extractor.extract_text("fixture", "generic").domain_payloads[0].domain == "generic"


def test_domain_provider_extractor_has_no_gemini_constructor_contract():
    parameters = inspect.signature(DomainProviderExtractor).parameters
    assert "api_key" not in parameters
    assert "fallback_models" not in parameters


def test_provider_response_cannot_bypass_scientific_admission():
    invalid = json.dumps({"source": "not-an-object"})
    extractor = DomainProviderExtractor(
        provider_adapter=FakeAdapter(outcomes=[invalid, invalid]),
    )
    with pytest.raises(Exception, match="validated|validation"):
        extractor.extract_text("fixture", "generic")


def test_fake_provider_tests_make_no_real_provider_invocation():
    adapter = FakeAdapter()
    DomainProviderExtractor(provider_adapter=adapter).extract_text("fixture", "generic")
    assert len(adapter.calls) == 1
