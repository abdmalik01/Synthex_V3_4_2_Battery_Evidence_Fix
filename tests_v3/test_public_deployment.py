from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.deployment import (
    DeploymentConfigurationError,
    PublicLimits,
    PublicUsageLedger,
    local_workspace,
    private_workspace,
    public_limits,
    public_mode_enabled,
    validate_public_uploads,
    verified_google_identity,
)
from synthex_platform.storage import JsonlArchiveStore


def test_public_mode_is_opt_in():
    assert not public_mode_enabled("")
    assert not public_mode_enabled("false")
    assert public_mode_enabled("true")


def test_private_paths_are_derived_from_verified_subject_not_email_or_input_path(tmp_path):
    issuer, subject = verified_google_identity({
        "iss": "https://accounts.google.com", "sub": "google-subject-123", "exp": 2_000_000_000,
    }, now=1_000_000_000)
    first = private_workspace(tmp_path, issuer=issuer, subject=subject)
    second = private_workspace(tmp_path, issuer=issuer, subject="another-user")
    assert first.owner_key != second.owner_key
    assert first.archive.parent.parent == first.jobs.parent == first.visual.parent
    assert first.archive.is_relative_to(tmp_path / "users")
    assert first.jobs != second.jobs
    assert "google-subject-123" not in str(first.root)
    assert local_workspace().archive == Path("data/archive/archives.jsonl")


@pytest.mark.parametrize("claims", [
    {"iss": "https://accounts.google.com", "sub": "", "exp": 2_000_000_000},
    {"iss": "https://untrusted.example", "sub": "abc", "exp": 2_000_000_000},
    {"iss": "https://accounts.google.com", "sub": "abc", "exp": 1},
    {"iss": "https://accounts.google.com", "sub": "abc"},
])
def test_public_identity_fails_closed(claims):
    with pytest.raises(DeploymentConfigurationError):
        verified_google_identity(claims, now=1_000_000_000)


def test_public_workspace_requires_absolute_persistent_root():
    with pytest.raises(DeploymentConfigurationError):
        private_workspace("data", issuer="https://accounts.google.com", subject="abc")


def test_private_archive_files_do_not_cross_user_boundary(tmp_path):
    alice = private_workspace(tmp_path, issuer="https://accounts.google.com", subject="alice")
    bob = private_workspace(tmp_path, issuer="https://accounts.google.com", subject="bob")
    alice_store = JsonlArchiveStore(alice.archive)
    bob_store = JsonlArchiveStore(bob.archive)
    archive = SynthexArchive(metadata=ArchiveMetadata(archive_id="alice-paper", domain="generic"))
    assert alice_store.append_unique(archive)
    assert alice_store.get("alice-paper") is not None
    assert bob_store.get("alice-paper") is None
    assert bob_store.count() == 0


def test_public_limits_reject_invalid_environment(monkeypatch):
    monkeypatch.setenv("SYNTHEX_PUBLIC_MAX_BATCH", "500")
    with pytest.raises(DeploymentConfigurationError):
        public_limits()


def test_public_uploads_validate_bytes_server_side():
    limits = PublicLimits(max_batch=1, max_pdf_bytes=10)
    validate_public_uploads([SimpleNamespace(name="small.pdf", size=10)], limits)
    with pytest.raises(ValueError, match="at most"):
        validate_public_uploads([SimpleNamespace(name="a.pdf", size=1), SimpleNamespace(name="b.pdf", size=1)], limits)
    with pytest.raises(ValueError, match="exceeds"):
        validate_public_uploads([SimpleNamespace(name="large.pdf", size=11)], limits)


def test_public_usage_reservation_enforces_user_and_global_limits(tmp_path):
    ledger = PublicUsageLedger(tmp_path)
    assert ledger.reserve(owner_key="alice", action="extract", per_user_limit=1, global_limit=2)
    assert not ledger.reserve(owner_key="alice", action="extract", per_user_limit=1, global_limit=2)
    assert ledger.reserve(owner_key="bob", action="extract", per_user_limit=1, global_limit=2)
    assert not ledger.reserve(owner_key="carol", action="extract", per_user_limit=1, global_limit=2)
    assert ledger.reserve(owner_key="alice", action="search", per_user_limit=1, global_limit=1)
    assert not ledger.reserve(owner_key="bob", action="search", per_user_limit=1, global_limit=1)
    assert len(ledger.log.read_all()) == 3


def test_public_usage_limit_is_atomic_across_concurrent_sessions(tmp_path):
    ledger = PublicUsageLedger(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda _: ledger.reserve(owner_key="same-user", action="extract", per_user_limit=2, global_limit=2),
            range(8),
        ))
    assert sum(results) == 2


def test_public_app_without_oidc_configuration_shows_no_workspace(monkeypatch):
    monkeypatch.setenv("SYNTHEX_PUBLIC_MODE", "true")
    monkeypatch.setenv("SYNTHEX_DATA_ROOT", "")
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    at = AppTest.from_file(app_file, default_timeout=30).run()
    assert not at.exception
    assert any("Sign-in is not configured" in item.value for item in at.error)
    assert not at.sidebar.radio


def test_public_app_uses_google_identity_and_hides_operator_pages(tmp_path, monkeypatch):
    class TestUser:
        is_logged_in = True

        def to_dict(self):
            return {"iss": "https://accounts.google.com", "sub": "tester", "exp": 2_000_000_000}

    monkeypatch.setenv("SYNTHEX_PUBLIC_MODE", "true")
    monkeypatch.setenv("SYNTHEX_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNTHEX_DEVELOPER_MODE", "true")
    monkeypatch.setattr(st, "secrets", {"auth": {
        "redirect_uri": "https://example.org/oauth2callback",
        "cookie_secret": "test-only",
        "google": {
            "client_id": "test-only", "client_secret": "test-only",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        },
    }})
    monkeypatch.setattr(st, "user", TestUser())
    app_file = Path(__file__).resolve().parents[1] / "platform_app.py"
    at = AppTest.from_file(app_file, default_timeout=30).run()
    assert not at.exception
    assert any(item.value == "Synthex" for item in at.title)
    assert "Developer · System audit" not in at.sidebar.radio[0].options
    assert "Explore Results" in at.sidebar.radio[0].options
    at.sidebar.radio[0].set_value("Analyze Papers").run()
    assert not at.exception
    assert any("Gemini provider" in item.value for item in at.caption)
    at.sidebar.radio[0].set_value("Gas Sensing Analytics").run()
    assert not at.exception
