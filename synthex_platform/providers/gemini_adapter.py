"""Gemini transport adapter implementing the provider-neutral contract."""

from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from typing import Any, Iterable

from .contracts import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorClass,
    ProviderModelIdentity,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    TRANSIENT_PROVIDER_ERRORS,
    redact_secrets,
    utc_now,
)
from .gemini_gateway import (
    GeminiGateway,
    ProviderFailureClass,
    classify_provider_failure,
)


_ERROR_MAP = {
    ProviderFailureClass.provider_unavailable: ProviderErrorClass.TRANSIENT_UNAVAILABLE,
    ProviderFailureClass.quota: ProviderErrorClass.RATE_LIMITED,
    ProviderFailureClass.authentication: ProviderErrorClass.AUTHENTICATION_FAILED,
    ProviderFailureClass.model_unavailable: ProviderErrorClass.INVALID_REQUEST,
    ProviderFailureClass.timeout: ProviderErrorClass.TIMEOUT,
    ProviderFailureClass.transport_failure: ProviderErrorClass.TRANSIENT_UNAVAILABLE,
    ProviderFailureClass.safety: ProviderErrorClass.CONTENT_BLOCKED,
    ProviderFailureClass.unexpected: ProviderErrorClass.UNKNOWN_PROVIDER_ERROR,
}


def _safe_raw_response(response: Any, text: str) -> Any:
    for name in ("to_json_dict", "model_dump"):
        method = getattr(response, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                pass
    return {"text": text}


def _usage(response: Any) -> ProviderUsage:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return ProviderUsage()
    return ProviderUsage(
        input_tokens=getattr(metadata, "prompt_token_count", None),
        output_tokens=getattr(metadata, "candidates_token_count", None),
        total_tokens=getattr(metadata, "total_token_count", None),
        cached_tokens=getattr(metadata, "cached_content_token_count", None),
    )


class GeminiAdapter(ProviderAdapter):
    provider_name = "gemini"

    def __init__(
        self,
        *,
        client: Any,
        model_id: str,
        mode: str = "benchmark",
        fallback_models: Iterable[str] | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        if not model_id or not model_id.strip():
            raise ValueError("Gemini model_id must be explicitly configured or discovered.")
        self.mode = mode
        self._configured_model_id = model_id.strip()
        self._gateway = GeminiGateway(
            client=client,
            preferred_model=self._configured_model_id,
            fallback_models=fallback_models,
            mode=mode,
        )
        self._capabilities = capabilities or ProviderCapabilities(
            text_input=True,
            structured_output=True,
            native_schema=False,
            repair=True,
        )
        self._last_response: ProviderResponse | None = None

    def _generate(self, request: ProviderRequest) -> ProviderResponse:
        requested_at = utc_now()
        started = perf_counter()
        config = {}
        if request.response_mime_type:
            config["response_mime_type"] = request.response_mime_type
        if request.phase == "primary":
            native = self._gateway.generate_primary(contents=request.contents, config=config)
        else:
            native = self._gateway.generate_pinned(
                contents=request.contents, config=config, phase=request.phase,
            )
        latency_ms = round((perf_counter() - started) * 1000.0, 3)
        responded_at = utc_now()
        text = (getattr(native, "text", "") or "")
        reported = getattr(native, "model_version", None)
        identity = ProviderModelIdentity(
            provider_name=self.provider_name,
            model_id=self._gateway.actual_model or self._configured_model_id,
            configured_model_id=self._configured_model_id,
            provider_reported_model_id=reported,
            model_version=reported,
        )
        response = ProviderResponse(
            text=text,
            raw_payload=_safe_raw_response(native, text),
            identity=identity,
            request_timestamp=requested_at,
            response_timestamp=responded_at,
            latency_ms=latency_ms,
            usage=_usage(native),
        )
        self._last_response = response
        return response

    def generate_candidate(self, request: ProviderRequest) -> ProviderResponse:
        if request.phase != "primary":
            request = ProviderRequest(
                contents=request.contents,
                response_mime_type=request.response_mime_type,
                input_mode=request.input_mode,
                phase="primary",
                metadata=request.metadata,
            )
        return self._generate(request)

    def repair_candidate(self, request: ProviderRequest) -> ProviderResponse:
        if request.phase != "schema_repair":
            request = ProviderRequest(
                contents=request.contents,
                response_mime_type=request.response_mime_type,
                input_mode=request.input_mode,
                phase="schema_repair",
                metadata=request.metadata,
            )
        return self._generate(request)

    def classify_error(self, error: BaseException) -> ProviderError:
        legacy = classify_provider_failure(error)
        normalized = _ERROR_MAP[legacy]
        audit = self._gateway.audit()
        last = audit.get("provider_failures", [])[-1] if audit.get("provider_failures") else {}
        provider_message = redact_secrets(
            last.get("provider_message") or type(error).__name__
        )
        return ProviderError(
            error_class=normalized,
            safe_message=provider_message,
            raw_diagnostic={
                "provider_failure_class": legacy.value,
                "provider_message": provider_message,
            },
            retryable=normalized in TRANSIENT_PROVIDER_ERRORS,
        )

    def get_model_identity(self) -> ProviderModelIdentity:
        if self._last_response:
            return self._last_response.identity
        return ProviderModelIdentity(
            self.provider_name,
            self._configured_model_id,
            configured_model_id=self._configured_model_id,
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def get_usage(self) -> ProviderUsage:
        return self._last_response.usage if self._last_response else ProviderUsage()

    def get_latency(self) -> float | None:
        return self._last_response.latency_ms if self._last_response else None

    def audit(self) -> dict[str, Any]:
        audit = self._gateway.audit()
        audit.update({
            "provider_name": self.provider_name,
            "model_identity": asdict(self.get_model_identity()),
            "capabilities": asdict(self.get_capabilities()),
            "usage": asdict(self.get_usage()),
            "latency_ms": self.get_latency(),
        })
        return audit
