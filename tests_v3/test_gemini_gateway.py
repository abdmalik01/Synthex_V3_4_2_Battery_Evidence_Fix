from __future__ import annotations

from dataclasses import dataclass

import pytest

from synthex_platform.providers import (
    GeminiGateway,
    GeminiModelsUnavailableError,
    ProviderFailureClass,
    classify_provider_failure,
    configured_gemini_models,
    probe_gemini_models,
)


@dataclass
class Response:
    text: str


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = {key: list(value) for key, value in outcomes.items()}
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return Response(outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


def unavailable(model: str) -> ProviderError:
    return ProviderError(f"{model} is temporarily unavailable", 503)


def test_preferred_success_uses_one_attempt_and_records_audit():
    client = FakeClient({"preferred": ["ok"], "fallback": ["unused"]})
    gateway = GeminiGateway(client=client, preferred_model="preferred", fallback_models=["fallback"])
    assert gateway.generate_primary(contents="prompt", config={}).text == "ok"
    assert [call["model"] for call in client.models.calls] == ["preferred"]
    assert gateway.audit()["actual_model"] == "preferred"
    assert gateway.audit()["fallback_occurred"] is False


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ({"m1": [unavailable("m1")], "m2": ["ok"], "m3": ["unused"]}, ["m1", "m2"]),
        ({"m1": [unavailable("m1")], "m2": [unavailable("m2")], "m3": ["ok"]}, ["m1", "m2", "m3"]),
    ],
)
def test_production_failover_is_ordered_and_bounded(outcomes, expected):
    client = FakeClient(outcomes)
    gateway = GeminiGateway(client=client, preferred_model="m1", fallback_models=["m2", "m3"])
    assert gateway.generate_primary(contents="prompt", config={}).text == "ok"
    assert [call["model"] for call in client.models.calls] == expected
    assert gateway.audit()["fallback_occurred"] is True


def test_all_models_unavailable_raises_typed_failure_once_per_model():
    client = FakeClient({model: [unavailable(model)] for model in ("m1", "m2", "m3")})
    gateway = GeminiGateway(client=client, preferred_model="m1", fallback_models=["m2", "m3"])
    with pytest.raises(GeminiModelsUnavailableError) as caught:
        gateway.generate_primary(contents="prompt", config={})
    assert [call["model"] for call in client.models.calls] == ["m1", "m2", "m3"]
    assert caught.value.audit["models_attempted"] == ["m1", "m2", "m3"]


def test_benchmark_mode_and_nonavailability_failures_do_not_fail_over():
    benchmark_client = FakeClient({"m1": [unavailable("m1")], "m2": ["must not run"]})
    benchmark = GeminiGateway(
        client=benchmark_client, preferred_model="m1", fallback_models=["m2"], mode="benchmark",
    )
    with pytest.raises(ProviderError):
        benchmark.generate_primary(contents="prompt", config={})
    assert [call["model"] for call in benchmark_client.models.calls] == ["m1"]

    auth_client = FakeClient({"m1": [ProviderError("invalid API key", 401)], "m2": ["must not run"]})
    production = GeminiGateway(client=auth_client, preferred_model="m1", fallback_models=["m2"])
    with pytest.raises(ProviderError):
        production.generate_primary(contents="prompt", config={})
    assert [call["model"] for call in auth_client.models.calls] == ["m1"]


def test_schema_repair_is_pinned_to_model_that_produced_primary_output():
    client = FakeClient({"m1": [unavailable("m1")], "m2": ["malformed", "repaired"]})
    gateway = GeminiGateway(client=client, preferred_model="m1", fallback_models=["m2"])
    assert gateway.generate_primary(contents="extract", config={}).text == "malformed"
    assert gateway.generate_pinned(contents="repair", config={}, phase="schema_repair").text == "repaired"
    assert [call["model"] for call in client.models.calls] == ["m1", "m2", "m2"]
    assert gateway.audit()["attempts"][-1]["phase"] == "schema_repair"


def test_configuration_is_deterministic_deduplicated_and_backward_compatible(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "preferred")
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    models = configured_gemini_models()
    assert models[0] == "preferred"
    assert len(models) == len(set(models))
    assert configured_gemini_models("a", ["b", "a", "b", "c"]) == ("a", "b", "c")


def test_provider_classification_and_audit_redact_api_keys():
    error = ProviderError("503 api_key=super-secret", 503)
    assert classify_provider_failure(error) is ProviderFailureClass.provider_unavailable
    client = FakeClient({"m1": [error]})
    gateway = GeminiGateway(client=client, preferred_model="m1", fallback_models=[])
    with pytest.raises(GeminiModelsUnavailableError):
        gateway.generate_primary(contents="prompt", config={})
    serialized = str(gateway.audit())
    assert "super-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_health_probe_is_explicit_bounded_and_offline_with_fake_client():
    client = FakeClient({"m1": ["GEMINI WORKS"], "m2": [unavailable("m2")]})
    rows = probe_gemini_models(client, ["m1", "m2"])
    assert [row["status"] for row in rows] == ["available", "unavailable"]
    assert len(client.models.calls) == 2
