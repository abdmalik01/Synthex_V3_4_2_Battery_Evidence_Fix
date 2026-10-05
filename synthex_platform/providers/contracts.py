"""Provider-neutral contracts for candidate generation and benchmark metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable
import re


ProviderMode = Literal["benchmark", "production"]


class ProviderErrorClass(str, Enum):
    TRANSIENT_UNAVAILABLE = "TRANSIENT_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
    CONTENT_BLOCKED = "CONTENT_BLOCKED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    REPAIR_UNAVAILABLE = "REPAIR_UNAVAILABLE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


TRANSIENT_PROVIDER_ERRORS = frozenset({
    ProviderErrorClass.TRANSIENT_UNAVAILABLE,
    ProviderErrorClass.RATE_LIMITED,
    ProviderErrorClass.TIMEOUT,
})


@dataclass(frozen=True)
class ProviderModelIdentity:
    provider_name: str
    model_id: str
    configured_model_id: str | None = None
    provider_reported_model_id: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.configured_model_id is None:
            object.__setattr__(self, "configured_model_id", self.model_id)


@dataclass(frozen=True)
class ProviderCapabilities:
    text_input: bool = True
    document_input: bool | None = None
    pdf_input: bool | None = None
    image_input: bool | None = None
    structured_output: bool | None = None
    native_schema: bool | None = None
    tool_use: bool | None = None
    repair: bool = True
    supported_actions: tuple[str, ...] = ()
    input_token_limit: int | None = None
    output_token_limit: int | None = None


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None


@dataclass(frozen=True)
class ProviderRequest:
    contents: Any
    response_mime_type: str | None = None
    input_mode: str = "text"
    phase: Literal["primary", "schema_repair"] = "primary"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    raw_payload: Any
    identity: ProviderModelIdentity
    request_timestamp: str
    response_timestamp: str
    latency_ms: float
    usage: ProviderUsage = field(default_factory=ProviderUsage)

    def metadata(self) -> dict[str, Any]:
        return {
            "identity": asdict(self.identity),
            "request_timestamp": self.request_timestamp,
            "response_timestamp": self.response_timestamp,
            "latency_ms": self.latency_ms,
            "usage": asdict(self.usage),
        }


@dataclass(frozen=True)
class ProviderError:
    error_class: ProviderErrorClass
    safe_message: str
    raw_diagnostic: dict[str, Any]
    retryable: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_NAMED_SECRET = re.compile(
    r"(?i)(api[_ -]?key|authorization|credential|access[_ -]?token|"
    r"refresh[_ -]?token|token|secret)(\s*[=:]\s*)([^\s,;'\"}]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")


def redact_secrets(value: str) -> str:
    """Redact common credential forms before diagnostic persistence."""
    redacted = _NAMED_SECRET.sub(r"\1\2[REDACTED]", value)
    redacted = _BEARER_SECRET.sub("Bearer [REDACTED]", redacted)
    return _GOOGLE_API_KEY.sub("[REDACTED_GOOGLE_API_KEY]", redacted)


def normalize_provider_error(error: BaseException) -> ProviderError:
    """Best-effort provider-neutral normalization for adapters and retry policy."""
    message = str(error)
    lowered = message.casefold()
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status in (401, 403) or "unauthenticated" in lowered or "api key" in lowered:
        category = ProviderErrorClass.AUTHENTICATION_FAILED
    elif status == 429 or "rate limit" in lowered or "quota" in lowered or "resource_exhausted" in lowered:
        category = ProviderErrorClass.RATE_LIMITED
    elif isinstance(error, TimeoutError) or "timed out" in lowered or "timeout" in lowered:
        category = ProviderErrorClass.TIMEOUT
    elif status == 413 or "context length" in lowered or "too many tokens" in lowered:
        category = ProviderErrorClass.CONTEXT_TOO_LARGE
    elif "safety" in lowered or "blocked" in lowered or "prohibited" in lowered:
        category = ProviderErrorClass.CONTENT_BLOCKED
    elif status in (400, 404, 422) or "invalid argument" in lowered or "model not found" in lowered:
        category = ProviderErrorClass.INVALID_REQUEST
    elif status == 503 or "unavailable" in lowered or "high demand" in lowered or isinstance(error, ConnectionError):
        category = ProviderErrorClass.TRANSIENT_UNAVAILABLE
    else:
        category = ProviderErrorClass.UNKNOWN_PROVIDER_ERROR
    safe = redact_secrets(message)[:500]
    return ProviderError(
        error_class=category,
        safe_message=safe,
        raw_diagnostic={"exception_type": type(error).__name__, "safe_message": safe},
        retryable=category in TRANSIENT_PROVIDER_ERRORS,
    )


@runtime_checkable
class ProviderAdapter(Protocol):
    provider_name: str
    mode: ProviderMode

    def generate_candidate(self, request: ProviderRequest) -> ProviderResponse: ...

    def repair_candidate(self, request: ProviderRequest) -> ProviderResponse: ...

    def classify_error(self, error: BaseException) -> ProviderError: ...

    def get_model_identity(self) -> ProviderModelIdentity: ...

    def get_capabilities(self) -> ProviderCapabilities: ...

    def get_usage(self) -> ProviderUsage: ...

    def get_latency(self) -> float | None: ...

    def audit(self) -> dict[str, Any]: ...
