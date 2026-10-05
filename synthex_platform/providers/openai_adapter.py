"""OpenAI Responses transport implementing the provider-neutral contract."""

from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from typing import Any

from .contracts import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderError,
    ProviderModelIdentity,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    normalize_provider_error,
    redact_secrets,
    utc_now,
)


def _safe_raw_response(response: Any, text: str) -> Any:
    for name in ("model_dump", "to_dict"):
        method = getattr(response, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                pass
    return {"output_text": text}


def _usage(response: Any) -> ProviderUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return ProviderUsage()
    details = getattr(usage, "input_tokens_details", None)
    return ProviderUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        cached_tokens=getattr(details, "cached_tokens", None) if details else None,
    )


def _text_format(request: ProviderRequest) -> dict[str, Any] | None:
    if request.response_schema is not None:
        return {
            "type": "json_schema",
            "name": request.response_schema_name or "synthex_response",
            "strict": True,
            "schema": request.response_schema,
        }
    if request.response_mime_type == "application/json":
        return {"type": "json_object"}
    return None


class OpenAIAdapter(ProviderAdapter):
    """Exact-model OpenAI adapter with no implicit fallback."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        client: Any,
        model_id: str,
        mode: str = "benchmark",
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        if mode not in {"benchmark", "production"}:
            raise ValueError("OpenAI adapter mode must be 'benchmark' or 'production'.")
        if not model_id or not model_id.strip():
            raise ValueError("OpenAI model_id must be explicitly configured.")
        self.client = client
        self.mode = mode
        self._configured_model_id = model_id.strip()
        self._capabilities = capabilities or ProviderCapabilities(
            text_input=True,
            structured_output=True,
            native_schema=True,
            repair=True,
        )
        self._last_response: ProviderResponse | None = None
        self._attempts: list[dict[str, Any]] = []

    def _generate(self, request: ProviderRequest) -> ProviderResponse:
        requested_at = utc_now()
        started = perf_counter()
        kwargs: dict[str, Any] = {
            "model": self._configured_model_id,
            "input": request.contents,
            "store": False,
        }
        text_format = _text_format(request)
        if text_format is not None:
            kwargs["text"] = {"format": text_format}
        try:
            native = self.client.responses.create(**kwargs)
        except Exception as error:
            normalized = self.classify_error(error)
            self._attempts.append({
                "order": len(self._attempts) + 1,
                "model": self._configured_model_id,
                "phase": request.phase,
                "status": "failed",
                "error_class": normalized.error_class.value,
                "provider_message": normalized.safe_message,
                "timestamp": utc_now(),
            })
            raise
        latency_ms = round((perf_counter() - started) * 1000.0, 3)
        text = getattr(native, "output_text", "") or ""
        status = getattr(native, "status", None)
        if not text and status == "incomplete":
            details = getattr(native, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "unknown"
            raise RuntimeError(f"OpenAI response incomplete: {reason}")
        if not text:
            raise RuntimeError("OpenAI response contained no output text; it may have been refused or blocked.")
        reported_model = getattr(native, "model", None)
        identity = ProviderModelIdentity(
            provider_name=self.provider_name,
            model_id=self._configured_model_id,
            configured_model_id=self._configured_model_id,
            provider_reported_model_id=reported_model,
            model_version=reported_model if reported_model != self._configured_model_id else None,
        )
        response = ProviderResponse(
            text=text,
            raw_payload=_safe_raw_response(native, text),
            identity=identity,
            request_timestamp=requested_at,
            response_timestamp=utc_now(),
            latency_ms=latency_ms,
            usage=_usage(native),
        )
        self._last_response = response
        self._attempts.append({
            "order": len(self._attempts) + 1,
            "model": self._configured_model_id,
            "provider_reported_model_id": reported_model,
            "phase": request.phase,
            "status": "succeeded",
            "timestamp": response.response_timestamp,
        })
        return response

    def generate_candidate(self, request: ProviderRequest) -> ProviderResponse:
        if request.phase != "primary":
            request = ProviderRequest(
                contents=request.contents,
                response_mime_type=request.response_mime_type,
                response_schema=request.response_schema,
                response_schema_name=request.response_schema_name,
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
                response_schema=request.response_schema,
                response_schema_name=request.response_schema_name,
                input_mode=request.input_mode,
                phase="schema_repair",
                metadata=request.metadata,
            )
        return self._generate(request)

    def classify_error(self, error: BaseException) -> ProviderError:
        normalized = normalize_provider_error(error)
        status = getattr(error, "status_code", None)
        code = getattr(error, "code", None)
        request_id = getattr(error, "request_id", None)
        safe_message = redact_secrets(normalized.safe_message)
        return ProviderError(
            error_class=normalized.error_class,
            safe_message=safe_message,
            raw_diagnostic={
                "exception_type": type(error).__name__,
                "status_code": status,
                "code": redact_secrets(str(code)) if code is not None else None,
                "request_id": redact_secrets(str(request_id)) if request_id is not None else None,
                "safe_message": safe_message,
            },
            retryable=normalized.retryable,
        )

    def get_model_identity(self) -> ProviderModelIdentity:
        if self._last_response is not None:
            return self._last_response.identity
        return ProviderModelIdentity(
            provider_name=self.provider_name,
            model_id=self._configured_model_id,
            configured_model_id=self._configured_model_id,
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def get_usage(self) -> ProviderUsage:
        return self._last_response.usage if self._last_response else ProviderUsage()

    def get_latency(self) -> float | None:
        return self._last_response.latency_ms if self._last_response else None

    def audit(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "model_identity": asdict(self.get_model_identity()),
            "capabilities": asdict(self.get_capabilities()),
            "usage": asdict(self.get_usage()),
            "latency_ms": self.get_latency(),
            "attempts": list(self._attempts),
            "fallback_occurred": False,
        }
