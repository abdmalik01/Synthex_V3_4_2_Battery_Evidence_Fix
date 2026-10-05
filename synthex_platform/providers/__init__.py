"""Bounded provider gateways and optional health diagnostics."""

from .contracts import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorClass,
    ProviderModelIdentity,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    normalize_provider_error,
    redact_secrets,
)
from .gemini_adapter import GeminiAdapter
from .openai_adapter import OpenAIAdapter

from .gemini_gateway import (
    DEFAULT_GEMINI_MODELS,
    GeminiGateway,
    GeminiModelsUnavailableError,
    ProviderFailureClass,
    classify_provider_failure,
    configured_gemini_credential_slots,
    configured_gemini_models,
    discover_gemini_models,
    is_general_text_gemini_model,
    probe_configured_gemini,
    probe_gemini_models,
)

__all__ = [
    "ProviderAdapter",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderErrorClass",
    "ProviderModelIdentity",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderUsage",
    "normalize_provider_error",
    "redact_secrets",
    "GeminiAdapter",
    "OpenAIAdapter",
    "DEFAULT_GEMINI_MODELS",
    "GeminiGateway",
    "GeminiModelsUnavailableError",
    "ProviderFailureClass",
    "classify_provider_failure",
    "configured_gemini_credential_slots",
    "configured_gemini_models",
    "discover_gemini_models",
    "is_general_text_gemini_model",
    "probe_configured_gemini",
    "probe_gemini_models",
]
