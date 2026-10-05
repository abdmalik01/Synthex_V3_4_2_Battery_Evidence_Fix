"""Narrow same-model transient retry for controlled live benchmark invocations."""

from __future__ import annotations

import json
from pathlib import Path
from time import sleep
from typing import Any, Callable

from synthex_platform.providers import (
    ProviderAdapter,
    normalize_provider_error,
)

from synthex_platform.providers.gemini_gateway import (
    ProviderFailureClass, classify_provider_failure,
)


def run_with_transient_retries(
    run: Callable[[], Any], *, model: str, ledger_path: str | Path,
    max_attempts: int = 3, wait: Callable[[float], None] = sleep,
) -> tuple[Any | None, dict[str, Any]]:
    if not 1 <= max_attempts <= 3:
        raise ValueError("Controlled benchmark retries must be between one and three total attempts")
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, Any] = {
        "model": model, "max_attempts": max_attempts,
        "credential_path": "primary", "fallback": False, "attempts": [],
    }
    for number in range(1, max_attempts + 1):
        try:
            result = run()
        except Exception as error:
            failure = classify_provider_failure(error)
            audit = getattr(error, "audit", {}) or {}
            payload_returned = any(
                item.get("phase") == "primary" and item.get("status") == "succeeded"
                for item in audit.get("attempts", [])
            )
            repair_count = sum(
                item.get("phase") == "schema_repair" for item in audit.get("attempts", [])
            )
            retryable = failure in {
                ProviderFailureClass.provider_unavailable, ProviderFailureClass.timeout,
            }
            ledger["attempts"].append({
                "attempt": number, "model": model, "status": failure.value,
                "payload_returned": payload_returned, "credential_path": "primary",
                "fallback": False, "schema_repair_count": repair_count,
            })
            ledger["status"] = (
                "LIVE_PAYLOAD_REPAIR_UNAVAILABLE" if retryable and payload_returned
                else "LIVE_UNAVAILABLE_AFTER_RETRIES" if retryable and number == max_attempts
                else "RETRYING_TRANSIENT" if retryable else "NON_TRANSIENT_FAILURE"
            )
            path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            if not retryable or number == max_attempts:
                if retryable:
                    return None, ledger
                raise
            wait(float(2 ** number))
            continue
        provider_audit = result.get("provider_audit", {}) if isinstance(result, dict) else {}
        diagnostics = result.get("extraction_diagnostics", {}) if isinstance(result, dict) else {}
        ledger["attempts"].append({
            "attempt": number,
            "model": provider_audit.get("actual_model") or model,
            "status": "payload_returned", "payload_returned": True,
            "credential_path": provider_audit.get("actual_credential_slot") or "primary",
            "fallback": bool(provider_audit.get("fallback_occurred")),
            "schema_repair_count": diagnostics.get("schema_repair_calls", 0),
        })
        ledger["status"] = "LIVE_PAYLOAD_RETURNED"
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        return result, ledger
    raise AssertionError("unreachable")


def run_provider_with_retries(
    run: Callable[[], Any],
    *,
    provider: str,
    model_id: str,
    run_id: str,
    ledger_path: str | Path,
    adapter: ProviderAdapter | None = None,
    max_attempts: int = 3,
    wait: Callable[[float], None] = sleep,
    raise_nontransient: bool = True,
) -> tuple[Any | None, dict[str, Any]]:
    """Provider-neutral, exact-model benchmark retries with no fallback."""
    if not 1 <= max_attempts <= 3:
        raise ValueError("Controlled benchmark retries must be between one and three total attempts")
    if adapter is not None:
        identity = adapter.get_model_identity()
        configured_model_id = identity.configured_model_id or identity.model_id
        if adapter.mode != "benchmark":
            raise ValueError("Provider benchmark retries require an adapter in benchmark mode")
        if identity.provider_name != provider or configured_model_id != model_id:
            raise ValueError("Retry metadata must exactly match the configured provider/model identity")
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, Any] = {
        "provider_name": provider,
        "model_id": model_id,
        "run_id": run_id,
        "mode": "benchmark",
        "max_attempts": max_attempts,
        "fallback_used": False,
        "attempts": [],
    }
    for number in range(1, max_attempts + 1):
        prior_attempt_count = 0
        if adapter is not None:
            prior_attempt_count = len(adapter.audit().get("attempts", []))
        try:
            result = run()
        except Exception as error:
            normalized = adapter.classify_error(error) if adapter is not None else normalize_provider_error(error)
            audit = adapter.audit() if adapter is not None else (getattr(error, "audit", {}) or {})
            current_attempt = audit.get("attempts", [])[prior_attempt_count:]
            payload_returned = any(
                item.get("phase") == "primary" and item.get("status") == "succeeded"
                for item in current_attempt
            )
            repair_count = sum(item.get("phase") == "schema_repair" for item in current_attempt)
            ledger["attempts"].append({
                "attempt_number": number,
                "provider_name": provider,
                "model_id": model_id,
                "provider_error_class": normalized.error_class.value,
                "provider_error_detail": normalized.raw_diagnostic,
                "payload_returned": payload_returned,
                "repair_count": repair_count,
                "fallback_used": False,
            })
            ledger["status"] = (
                "LIVE_PAYLOAD_REPAIR_UNAVAILABLE" if payload_returned
                else "LIVE_UNAVAILABLE_AFTER_RETRIES" if normalized.retryable and number == max_attempts
                else "RETRYING_TRANSIENT" if normalized.retryable
                else "PROVIDER_ERROR_WITH_NO_PAYLOAD"
            )
            path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            if not normalized.retryable or payload_returned or number == max_attempts:
                if payload_returned or normalized.retryable:
                    return None, ledger
                if raise_nontransient:
                    raise
                return None, ledger
            wait(float(2 ** number))
            continue
        provider_audit = result.get("provider_audit", {}) if isinstance(result, dict) else {}
        identity = provider_audit.get("model_identity", {})
        if provider_audit.get("fallback_occurred"):
            raise RuntimeError("Benchmark provider unexpectedly reported fallback")
        actual_model_id = identity.get("model_id") or model_id
        configured_model_id = identity.get("configured_model_id") or model_id
        if actual_model_id != model_id or configured_model_id != model_id:
            raise RuntimeError("Benchmark provider returned a different model identity")
        ledger["attempts"].append({
            "attempt_number": number,
            "provider_name": provider,
            "model_id": actual_model_id,
            "configured_model_id": configured_model_id,
            "provider_reported_model_id": identity.get("provider_reported_model_id"),
            "payload_returned": True,
            "repair_count": result.get("extraction_diagnostics", {}).get("schema_repair_calls", 0),
            "latency_ms": provider_audit.get("latency_ms"),
            "usage": provider_audit.get("usage"),
            "fallback_used": False,
        })
        ledger["status"] = "LIVE_PAYLOAD_RETURNED"
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        return result, ledger
    raise AssertionError("unreachable")
