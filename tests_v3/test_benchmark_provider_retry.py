from __future__ import annotations

import pytest

from synthex_platform.benchmarks.provider_retry import run_with_transient_retries


def test_same_model_transient_retry_records_attempts(tmp_path):
    attempts = []
    waits = []

    def run():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("503 UNAVAILABLE: high demand")
        return {"provider_audit": {"actual_model": "gemini-3.5-flash"}, "extraction_diagnostics": {"schema_repair_calls": 0}}

    result, ledger = run_with_transient_retries(
        run, model="gemini-3.5-flash", ledger_path=tmp_path / "ledger.json", wait=waits.append,
    )
    assert result is not None
    assert len(ledger["attempts"]) == 3
    assert {item["model"] for item in ledger["attempts"]} == {"gemini-3.5-flash"}
    assert all(item["credential_path"] == "primary" and not item["fallback"] for item in ledger["attempts"])
    assert waits == [2.0, 4.0]


def test_nontransient_validation_failure_is_not_retried(tmp_path):
    calls = []

    def run():
        calls.append(1)
        raise ValueError("Scientific benchmark mismatch")

    with pytest.raises(ValueError, match="Scientific benchmark mismatch"):
        run_with_transient_retries(run, model="gemini-3.5-flash", ledger_path=tmp_path / "ledger.json", wait=lambda _: None)
    assert len(calls) == 1


def test_repair_unavailable_preserves_primary_payload_status(tmp_path):
    class RepairUnavailable(RuntimeError):
        pass

    def run():
        error = RepairUnavailable("503 UNAVAILABLE: high demand during schema repair")
        error.audit = {"attempts": [
            {"phase": "primary", "status": "succeeded"},
            {"phase": "schema_repair", "status": "failed"},
        ]}
        raise error

    result, ledger = run_with_transient_retries(
        run, model="gemini-3.5-flash", ledger_path=tmp_path / "ledger.json",
        max_attempts=1, wait=lambda _: None,
    )
    assert result is None
    assert ledger["status"] == "LIVE_PAYLOAD_REPAIR_UNAVAILABLE"
    assert ledger["attempts"][0]["payload_returned"] is True
    assert ledger["attempts"][0]["schema_repair_count"] == 1
