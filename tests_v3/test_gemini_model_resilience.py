from __future__ import annotations

import pytest

from synthex_platform.providers.gemini_gateway import (
    DEFAULT_GEMINI_MODELS,
    GeminiGateway,
    GeminiModelsUnavailableError,
    configured_gemini_models,
)


class _Models:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        outcome = self.outcomes.get(model)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Client:
    def __init__(self, outcomes):
        self.models = _Models(outcomes)


class _Response:
    text = "OK"


def test_default_chain_spans_flash_lite_and_25_family():
    assert DEFAULT_GEMINI_MODELS == (
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    )
    assert configured_gemini_models()[0] == "gemini-3.8-flash"


def test_production_falls_back_once_per_model_until_success():
    client = _Client({
        "gemini-3.8-flash": RuntimeError("503 provider unavailable"),
        "gemini-3.7-flash": RuntimeError("model not found 404"),
        "gemini-3.6-flash": _Response(),
    })
    gateway = GeminiGateway(
        client=client,
        preferred_model="gemini-3.8-flash",
        fallback_models=("gemini-3.7-flash", "gemini-3.6-flash"),
        mode="production",
        credential_clients=(),
    )

    result = gateway.generate_primary(contents="x", config={})

    assert isinstance(result, _Response)
    assert client.models.calls == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"]
    assert gateway.actual_model == "gemini-3.6-flash"


def test_unavailable_error_exposes_secret_safe_per_model_diagnostics():
    client = _Client({
        "m1": RuntimeError("503 high demand"),
        "m2": RuntimeError("404 model not found"),
    })
    gateway = GeminiGateway(
        client=client,
        preferred_model="m1",
        fallback_models=("m2",),
        mode="production",
        credential_clients=(),
    )

    with pytest.raises(GeminiModelsUnavailableError) as exc_info:
        gateway.generate_primary(contents="x", config={})

    error = exc_info.value
    assert "m1: provider_unavailable" in str(error)
    assert "m2: model_unavailable" in str(error)
    assert error.audit["failure_summary"] == error.failure_summary
    assert error.audit["models_attempted"] == ["m1", "m2"]


def test_benchmark_mode_remains_pinned_to_requested_model():
    client = _Client({"m1": RuntimeError("503 unavailable"), "m2": _Response()})
    gateway = GeminiGateway(
        client=client,
        preferred_model="m1",
        fallback_models=("m2",),
        mode="benchmark",
        credential_clients=(),
    )

    with pytest.raises(GeminiModelsUnavailableError):
        gateway.generate_primary(contents="x", config={})

    assert client.models.calls == ["m1"]
    assert gateway.model_chain == ("m1",)
