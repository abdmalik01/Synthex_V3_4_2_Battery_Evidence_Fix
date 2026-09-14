"""Bounded provider gateways and optional health diagnostics."""

from .gemini_gateway import (
    DEFAULT_GEMINI_MODELS,
    GeminiGateway,
    GeminiModelsUnavailableError,
    ProviderFailureClass,
    classify_provider_failure,
    configured_gemini_models,
    probe_configured_gemini,
    probe_gemini_models,
)

__all__ = [
    "DEFAULT_GEMINI_MODELS",
    "GeminiGateway",
    "GeminiModelsUnavailableError",
    "ProviderFailureClass",
    "classify_provider_failure",
    "configured_gemini_models",
    "probe_configured_gemini",
    "probe_gemini_models",
]
