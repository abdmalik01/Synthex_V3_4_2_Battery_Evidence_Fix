from __future__ import annotations

from types import SimpleNamespace

import pytest

from synthex_platform.providers.gemini_gateway import (
    GeminiGateway,
    configured_gemini_credential_slots,
)


class FakeProviderError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if not self.outcomes:
            raise AssertionError("Unexpected provider call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


def response(text="ok"):
    return SimpleNamespace(text=text)


def test_production_rotates_credentials_on_quota_without_changing_model():
    primary = FakeClient([FakeProviderError(429, "RESOURCE_EXHAUSTED quota")])
    second = FakeClient([response("from second")])
    gateway = GeminiGateway(
        client=primary,
        preferred_model="model-a",
        fallback_models=("model-b",),
        mode="production",
        credential_clients=(("GEMINI_API_KEY_2", second),),
    )

    result = gateway.generate_primary(contents="paper", config={})

    assert result.text == "from second"
    assert primary.models.calls == ["model-a"]
    assert second.models.calls == ["model-a"]
    audit = gateway.audit()
    assert audit["actual_model"] == "model-a"
    assert audit["actual_credential_slot"] == "GEMINI_API_KEY_2"
    assert audit["credential_failover_occurred"] is True
    assert audit["fallback_occurred"] is False
    assert audit["configured_credential_count"] == 2


def test_provider_unavailable_falls_back_model_without_burning_second_key():
    primary = FakeClient([
        FakeProviderError(503, "UNAVAILABLE high demand"),
        response("fallback model worked"),
    ])
    second = FakeClient([response("should not be used")])
    gateway = GeminiGateway(
        client=primary,
        preferred_model="model-a",
        fallback_models=("model-b",),
        mode="production",
        credential_clients=(("GEMINI_API_KEY_2", second),),
    )

    result = gateway.generate_primary(contents="paper", config={})

    assert result.text == "fallback model worked"
    assert primary.models.calls == ["model-a", "model-b"]
    assert second.models.calls == []
    audit = gateway.audit()
    assert audit["actual_model"] == "model-b"
    assert audit["actual_credential_slot"] == "primary"
    assert audit["fallback_occurred"] is True
    assert audit["credential_failover_occurred"] is False


def test_benchmark_mode_never_rotates_credentials():
    primary_error = FakeProviderError(429, "RESOURCE_EXHAUSTED quota")
    primary = FakeClient([primary_error])
    second = FakeClient([response("must not run")])
    gateway = GeminiGateway(
        client=primary,
        preferred_model="model-a",
        fallback_models=("model-b",),
        mode="benchmark",
        credential_clients=(("GEMINI_API_KEY_2", second),),
    )

    with pytest.raises(FakeProviderError) as excinfo:
        gateway.generate_primary(contents="paper", config={})

    assert excinfo.value is primary_error
    assert primary.models.calls == ["model-a"]
    assert second.models.calls == []
    audit = gateway.audit()
    assert audit["configured_credential_count"] == 1
    assert audit["configured_model_order"] == ["model-a"]


def test_pinned_secondary_call_can_advance_to_next_credential_after_quota():
    primary = FakeClient([
        response("primary ok"),
        FakeProviderError(429, "quota exhausted during repair"),
    ])
    second = FakeClient([response("repair ok")])
    gateway = GeminiGateway(
        client=primary,
        preferred_model="model-a",
        mode="production",
        credential_clients=(("GEMINI_API_KEY_2", second),),
    )

    gateway.generate_primary(contents="paper", config={})
    repaired = gateway.generate_pinned(contents="repair", config={}, phase="schema_repair")

    assert repaired.text == "repair ok"
    assert primary.models.calls == ["model-a", "model-a"]
    assert second.models.calls == ["model-a"]
    audit = gateway.audit()
    assert audit["actual_model"] == "model-a"
    assert audit["actual_credential_slot"] == "GEMINI_API_KEY_2"
    assert audit["credential_failover_occurred"] is True


def test_configured_credential_slots_expose_names_not_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-primary")
    monkeypatch.setenv("GEMINI_API_KEY_2", "secret-two")
    monkeypatch.setenv("GEMINI_API_KEY_3", "secret-three")

    slots = configured_gemini_credential_slots()

    assert slots == ("primary", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")
    rendered = repr(slots)
    assert "secret-primary" not in rendered
    assert "secret-two" not in rendered
    assert "secret-three" not in rendered
