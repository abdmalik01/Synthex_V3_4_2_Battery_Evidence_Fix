"""Auditable, bounded Gemini model selection for Synthex production requests."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import os
import re
from time import perf_counter
from typing import Any, Iterable, Literal

try:
    from google import genai
except ImportError:  # pragma: no cover - permits offline platform use
    genai = None


DEFAULT_GEMINI_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
)


class ProviderFailureClass(str, Enum):
    provider_unavailable = "provider_unavailable"
    quota = "quota"
    authentication = "authentication"
    model_unavailable = "model_unavailable"
    timeout = "timeout"
    transport_failure = "transport_failure"
    safety = "safety"
    unexpected = "unexpected_error"


_FAILOVER_ELIGIBLE = {
    ProviderFailureClass.provider_unavailable,
    ProviderFailureClass.model_unavailable,
    ProviderFailureClass.timeout,
    ProviderFailureClass.transport_failure,
}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|key|credential|token)(\s*[=:]\s*)([^\s,;'\"}]+)"
)


def _safe_message(error: BaseException) -> str:
    return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", str(error))[:500]


def classify_provider_failure(error: BaseException) -> ProviderFailureClass:
    """Classify provider failures without treating scientific validation as availability."""
    message = str(error).casefold()
    name = type(error).__name__.casefold()
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status in (401, 403) or "unauthenticated" in message or "permission_denied" in message or "api key" in message:
        return ProviderFailureClass.authentication
    if status == 429 or "429" in message or "resource_exhausted" in message or "quota" in message:
        return ProviderFailureClass.quota
    if "safety" in message or "blocked" in message or "prohibited" in message:
        return ProviderFailureClass.safety
    if status == 503 or "503" in message or "unavailable" in message or "high demand" in message:
        return ProviderFailureClass.provider_unavailable
    if status == 404 or "404" in message or "model not found" in message or "model is not available" in message:
        return ProviderFailureClass.model_unavailable
    if isinstance(error, TimeoutError) or "timeout" in name or "timed out" in message:
        return ProviderFailureClass.timeout
    if isinstance(error, (ConnectionError, OSError)) or "connection" in name or "transport" in message:
        return ProviderFailureClass.transport_failure
    return ProviderFailureClass.unexpected


def _deduplicate_models(models: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered = []
    for value in models:
        model = str(value).strip()
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return tuple(ordered)


def configured_gemini_models(
    preferred_model: str | None = None,
    fallback_models: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Resolve one preferred model followed by an approved deterministic fallback chain."""
    preferred = preferred_model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if fallback_models is None:
        configured = os.getenv("GEMINI_FALLBACK_MODELS")
        fallback_models = (
            configured.split(",") if configured is not None
            else DEFAULT_GEMINI_MODELS
        )
    return _deduplicate_models((preferred, *fallback_models))


class GeminiModelsUnavailableError(RuntimeError):
    """Every permitted model failed for a provider-level availability reason."""

    def __init__(self, audit: dict[str, Any]):
        self.audit = audit
        super().__init__("All approved Gemini models were unavailable after one bounded attempt each.")


class GeminiGateway:
    """Try approved models once in production; pin one model in benchmark mode."""

    def __init__(
        self,
        *,
        client: Any,
        preferred_model: str | None = None,
        fallback_models: Iterable[str] | None = None,
        mode: Literal["production", "benchmark"] = "production",
    ) -> None:
        if mode not in {"production", "benchmark"}:
            raise ValueError("Gemini gateway mode must be 'production' or 'benchmark'.")
        self.client = client
        self.mode = mode
        chain = configured_gemini_models(preferred_model, fallback_models)
        self.preferred_model = chain[0]
        self.model_chain = chain if mode == "production" else chain[:1]
        self.actual_model: str | None = None
        self._attempts: list[dict[str, Any]] = []

    def _record(
        self,
        *,
        model: str,
        phase: str,
        status: str,
        failure_class: ProviderFailureClass | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._attempts.append({
            "order": len(self._attempts) + 1,
            "model": model,
            "phase": phase,
            "status": status,
            "failure_class": failure_class.value if failure_class else None,
            "provider_message": _safe_message(error) if error else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def generate_primary(self, *, contents: Any, config: Any) -> Any:
        """Issue one primary call per eligible model, with no same-model retry."""
        for model in self.model_chain:
            try:
                response = self.client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as error:
                failure_class = classify_provider_failure(error)
                self._record(
                    model=model, phase="primary", status="failed",
                    failure_class=failure_class, error=error,
                )
                if self.mode == "production" and failure_class in _FAILOVER_ELIGIBLE:
                    continue
                raise
            self.actual_model = model
            self._record(model=model, phase="primary", status="succeeded")
            return response
        raise GeminiModelsUnavailableError(self.audit())

    def generate_pinned(self, *, contents: Any, config: Any, phase: str) -> Any:
        """Run repair/secondary calls on the selected model without cross-model failover."""
        model = self.actual_model or self.preferred_model
        try:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as error:
            self._record(
                model=model, phase=phase, status="failed",
                failure_class=classify_provider_failure(error), error=error,
            )
            raise
        self._record(model=model, phase=phase, status="succeeded")
        return response

    def audit(self) -> dict[str, Any]:
        attempted_models = _deduplicate_models(
            item["model"] for item in self._attempts if item["phase"] == "primary"
        )
        return {
            "mode": self.mode,
            "requested_model": self.preferred_model,
            "actual_model": self.actual_model,
            "configured_model_order": list(self.model_chain),
            "models_attempted": list(attempted_models),
            "fallback_occurred": bool(self.actual_model and self.actual_model != self.preferred_model),
            "attempts": [dict(item) for item in self._attempts],
            "provider_failures": [
                {key: item[key] for key in ("model", "phase", "failure_class", "provider_message")}
                for item in self._attempts if item["status"] == "failed"
            ],
        }


def probe_gemini_models(client: Any, models: Iterable[str]) -> tuple[dict[str, Any], ...]:
    """Run one tiny, explicit health request per model; never imply extraction readiness."""
    results = []
    for model in _deduplicate_models(models):
        started = perf_counter()
        try:
            response = client.models.generate_content(
                model=model,
                contents="Reply with exactly: GEMINI WORKS",
                config={"temperature": 0, "automatic_function_calling": {"disable": True}},
            )
            returned_text = (getattr(response, "text", "") or "").strip()
            status = "available" if returned_text == "GEMINI WORKS" else "unexpected_response"
            failure_class = None
            provider_message = None
        except Exception as error:
            returned_text = ""
            failure_class = classify_provider_failure(error).value
            status = "unavailable"
            provider_message = _safe_message(error)
        results.append({
            "model": model,
            "status": status,
            "returned_text": returned_text,
            "failure_class": failure_class,
            "provider_message": provider_message,
            "latency_seconds": round(perf_counter() - started, 3),
        })
    return tuple(results)


def probe_configured_gemini(
    *, preferred_model: str | None = None, fallback_models: Iterable[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Explicit environment-backed health check for the Advanced UI only."""
    if genai is None:
        raise RuntimeError("google-genai is not installed.")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing.")
    client = genai.Client(api_key=api_key)
    return probe_gemini_models(client, configured_gemini_models(preferred_model, fallback_models))
