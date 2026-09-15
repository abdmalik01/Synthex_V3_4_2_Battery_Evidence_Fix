"""Auditable, bounded Gemini model and credential selection for Synthex requests."""

from __future__ import annotations

from collections import Counter
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


# Production fallback order deliberately spans model families instead of relying only on
# neighbouring Flash releases. Benchmark mode remains pinned to the requested model.
DEFAULT_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
)
MAX_GEMINI_CREDENTIAL_SLOTS = 10


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
_CREDENTIAL_FAILOVER_ELIGIBLE = {
    ProviderFailureClass.quota,
    ProviderFailureClass.authentication,
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
        fallback_models = configured.split(",") if configured is not None else DEFAULT_GEMINI_MODELS
    return _deduplicate_models((preferred, *fallback_models))


def configured_gemini_credential_slots() -> tuple[str, ...]:
    """Return configured credential slot names without ever exposing credential values."""
    slots: list[str] = []
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        slots.append("primary")
    for index in range(2, MAX_GEMINI_CREDENTIAL_SLOTS + 1):
        if os.getenv(f"GEMINI_API_KEY_{index}"):
            slots.append(f"GEMINI_API_KEY_{index}")
    return tuple(slots)


def _environment_credential_clients() -> tuple[tuple[str, Any], ...]:
    """Build numbered fallback clients for live production calls only.

    Pytest may run with a real local .env present. Never let offline/mocked tests silently
    instantiate fallback clients from those credentials and make network calls.
    """
    if genai is None or os.getenv("PYTEST_CURRENT_TEST"):
        return ()
    primary_value = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    seen_values = {primary_value} if primary_value else set()
    clients: list[tuple[str, Any]] = []
    for index in range(2, MAX_GEMINI_CREDENTIAL_SLOTS + 1):
        slot = f"GEMINI_API_KEY_{index}"
        value = os.getenv(slot)
        if not value or value in seen_values:
            continue
        seen_values.add(value)
        clients.append((slot, genai.Client(api_key=value)))
    return tuple(clients)


def summarize_provider_failures(audit: dict[str, Any]) -> str:
    """Return a compact, secret-safe explanation suitable for CLI/Streamlit display."""
    failures = audit.get("provider_failures") or []
    if not failures:
        return "No provider failure details were recorded."

    counts = Counter(item.get("failure_class") or "unknown" for item in failures)
    count_text = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    model_text = "; ".join(
        f"{item.get('model', 'unknown')}: {item.get('failure_class') or 'unknown'}"
        + (f" ({item.get('provider_message')})" if item.get("provider_message") else "")
        for item in failures
    )
    return f"Failure summary: {count_text}. Attempts: {model_text}"[:2000]


class GeminiModelsUnavailableError(RuntimeError):
    """Every permitted model failed for a provider-level availability reason."""

    def __init__(self, audit: dict[str, Any]):
        self.audit = audit
        self.failure_summary = summarize_provider_failures(audit)
        super().__init__(
            "All approved Gemini models were unavailable after one bounded attempt each. "
            + self.failure_summary
        )


class GeminiGateway:
    """Bounded model failover plus production-only credential failover.

    Model failover handles provider/model availability failures. Credential failover handles
    quota/authentication failures and never exposes key values in diagnostics. Benchmark mode
    remains pinned to the caller-supplied primary credential and one model.
    """

    def __init__(
        self,
        *,
        client: Any,
        preferred_model: str | None = None,
        fallback_models: Iterable[str] | None = None,
        mode: Literal["production", "benchmark"] = "production",
        credential_clients: Iterable[tuple[str, Any]] | None = None,
    ) -> None:
        if mode not in {"production", "benchmark"}:
            raise ValueError("Gemini gateway mode must be 'production' or 'benchmark'.")
        self.client = client
        self.mode = mode
        chain = configured_gemini_models(preferred_model, fallback_models)
        self.preferred_model = chain[0]
        self.model_chain = chain if mode == "production" else chain[:1]
        extras = tuple(credential_clients) if credential_clients is not None else _environment_credential_clients()
        self._credential_clients: tuple[tuple[str, Any], ...] = (
            (("primary", client), *extras) if mode == "production" else (("primary", client),)
        )
        self.actual_model: str | None = None
        self.actual_credential_slot: str | None = None
        self._disabled_credential_slots: set[str] = set()
        self._attempts: list[dict[str, Any]] = []

    def _record(
        self,
        *,
        model: str,
        phase: str,
        status: str,
        credential_slot: str = "primary",
        failure_class: ProviderFailureClass | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._attempts.append({
            "order": len(self._attempts) + 1,
            "model": model,
            "credential_slot": credential_slot,
            "phase": phase,
            "status": status,
            "failure_class": failure_class.value if failure_class else None,
            "provider_message": _safe_message(error) if error else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _available_credentials(self, *, preferred_slot: str | None = None) -> tuple[tuple[str, Any], ...]:
        active = [item for item in self._credential_clients if item[0] not in self._disabled_credential_slots]
        if preferred_slot:
            active.sort(key=lambda item: item[0] != preferred_slot)
        return tuple(active)

    def generate_primary(self, *, contents: Any, config: Any) -> Any:
        """Issue bounded calls: rotate credentials only for quota/auth, models only for availability."""
        last_credential_error: BaseException | None = None
        for model in self.model_chain:
            credentials = self._available_credentials()
            if not credentials and last_credential_error is not None:
                raise last_credential_error
            model_should_fallback = False
            for credential_slot, client in credentials:
                try:
                    response = client.models.generate_content(model=model, contents=contents, config=config)
                except Exception as error:
                    failure_class = classify_provider_failure(error)
                    self._record(
                        model=model,
                        credential_slot=credential_slot,
                        phase="primary",
                        status="failed",
                        failure_class=failure_class,
                        error=error,
                    )
                    if self.mode == "production" and failure_class in _CREDENTIAL_FAILOVER_ELIGIBLE:
                        self._disabled_credential_slots.add(credential_slot)
                        last_credential_error = error
                        continue
                    if self.mode == "production" and failure_class in _FAILOVER_ELIGIBLE:
                        model_should_fallback = True
                        break
                    raise
                self.actual_model = model
                self.actual_credential_slot = credential_slot
                self.client = client
                self._record(
                    model=model,
                    credential_slot=credential_slot,
                    phase="primary",
                    status="succeeded",
                )
                return response
            if model_should_fallback:
                continue
            if last_credential_error is not None and not self._available_credentials():
                raise last_credential_error
        raise GeminiModelsUnavailableError(self.audit())

    def generate_pinned(self, *, contents: Any, config: Any, phase: str) -> Any:
        """Run repair/secondary calls on the selected model, allowing only credential failover in production."""
        model = self.actual_model or self.preferred_model
        last_credential_error: BaseException | None = None
        credentials = self._available_credentials(preferred_slot=self.actual_credential_slot)
        if not credentials and self.actual_credential_slot:
            credentials = tuple(item for item in self._credential_clients if item[0] == self.actual_credential_slot)
        for credential_slot, client in credentials:
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as error:
                failure_class = classify_provider_failure(error)
                self._record(
                    model=model,
                    credential_slot=credential_slot,
                    phase=phase,
                    status="failed",
                    failure_class=failure_class,
                    error=error,
                )
                if self.mode == "production" and failure_class in _CREDENTIAL_FAILOVER_ELIGIBLE:
                    self._disabled_credential_slots.add(credential_slot)
                    last_credential_error = error
                    continue
                raise
            self.client = client
            self.actual_credential_slot = credential_slot
            self._record(
                model=model,
                credential_slot=credential_slot,
                phase=phase,
                status="succeeded",
            )
            return response
        if last_credential_error is not None:
            raise last_credential_error
        raise RuntimeError("No usable Gemini credential remained for the pinned provider call.")

    def audit(self) -> dict[str, Any]:
        attempted_models = _deduplicate_models(
            item["model"] for item in self._attempts if item["phase"] == "primary"
        )
        credential_slots_attempted = tuple(dict.fromkeys(item["credential_slot"] for item in self._attempts))
        provider_failures = [
            {
                key: item[key]
                for key in ("model", "credential_slot", "phase", "failure_class", "provider_message")
            }
            for item in self._attempts if item["status"] == "failed"
        ]
        audit = {
            "mode": self.mode,
            "requested_model": self.preferred_model,
            "actual_model": self.actual_model,
            "configured_model_order": list(self.model_chain),
            "models_attempted": list(attempted_models),
            "fallback_occurred": bool(self.actual_model and self.actual_model != self.preferred_model),
            "configured_credential_count": len(self._credential_clients),
            "credential_slots_attempted": list(credential_slots_attempted),
            "actual_credential_slot": self.actual_credential_slot,
            "credential_failover_occurred": bool(
                self.actual_credential_slot and self.actual_credential_slot != "primary"
            ),
            "attempts": [dict(item) for item in self._attempts],
            "provider_failures": provider_failures,
        }
        audit["failure_summary"] = summarize_provider_failures(audit)
        return audit


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
    """Explicit health check for the primary environment credential only."""
    if genai is None:
        raise RuntimeError("google-genai is not installed.")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing.")
    client = genai.Client(api_key=api_key)
    return probe_gemini_models(client, configured_gemini_models(preferred_model, fallback_models))
