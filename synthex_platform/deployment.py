"""Fail-closed public deployment boundaries for the Streamlit workspace.

The local research application retains its historical paths. A public, single-
server deployment uses a mounted durable data root and one workspace per OIDC
subject; user-controlled labels are never used as filesystem path components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from synthex_platform.storage.atomic_jsonl import JsonlLog


_TRUE_VALUES = {"1", "true", "yes", "on"}


class DeploymentConfigurationError(ValueError):
    """A public deployment is missing a required security boundary."""


class IdentityExpiredError(DeploymentConfigurationError):
    """An OIDC identity cookie outlived the provider's identity token."""


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    archive: Path
    jobs: Path
    visual: Path
    graph: Path
    search_cache: Path
    owner_key: str | None = None


@dataclass(frozen=True)
class PublicLimits:
    max_batch: int = 3
    max_pdf_bytes: int = 25 * 1024 * 1024
    extracts_per_user_day: int = 3
    extracts_global_day: int = 30
    searches_per_user_day: int = 10
    searches_global_day: int = 100


def public_mode_enabled(value: str | None = None) -> bool:
    raw = os.getenv("SYNTHEX_PUBLIC_MODE", "") if value is None else value
    return str(raw).strip().casefold() in _TRUE_VALUES


def verified_google_identity(claims: Mapping[str, Any], *, now: float | None = None) -> tuple[str, str]:
    """Require the immutable, unexpired identity claims needed for isolation."""
    issuer = str(claims.get("iss") or "").strip()
    subject = str(claims.get("sub") or "").strip()
    if issuer not in {"accounts.google.com", "https://accounts.google.com"} or not subject:
        raise DeploymentConfigurationError("A verified Google identity is required")
    try:
        expires_at = int(claims.get("exp"))
    except (TypeError, ValueError) as exc:
        raise DeploymentConfigurationError("The identity expiry is unavailable") from exc
    if expires_at <= (time.time() if now is None else now):
        raise IdentityExpiredError("The identity has expired")
    return issuer, subject


def _workspace_paths(root: Path, *, owner_key: str | None = None) -> WorkspacePaths:
    return WorkspacePaths(
        root=root,
        archive=root / "archive" / "archives.jsonl",
        jobs=root / "jobs",
        visual=root / "archive",
        graph=root / "graph",
        search_cache=root / "search_cache",
        owner_key=owner_key,
    )


def local_workspace() -> WorkspacePaths:
    return _workspace_paths(Path("data"))


def private_workspace(data_root: str | Path, *, issuer: str, subject: str) -> WorkspacePaths:
    root = Path(data_root)
    if not root.is_absolute():
        raise DeploymentConfigurationError("SYNTHEX_DATA_ROOT must be an absolute path")
    if not issuer.strip() or not subject.strip():
        raise DeploymentConfigurationError("A verified OIDC issuer and subject are required")
    owner_key = sha256(f"{issuer.strip()}\0{subject.strip()}".encode("utf-8")).hexdigest()
    return _workspace_paths(root.resolve() / "users" / owner_key, owner_key=owner_key)


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise DeploymentConfigurationError(f"{name} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise DeploymentConfigurationError(f"{name} must be between 1 and {maximum}")
    return value


def public_limits() -> PublicLimits:
    return PublicLimits(
        max_batch=_positive_int("SYNTHEX_PUBLIC_MAX_BATCH", 3, maximum=20),
        max_pdf_bytes=_positive_int("SYNTHEX_PUBLIC_MAX_PDF_MB", 25, maximum=200) * 1024 * 1024,
        extracts_per_user_day=_positive_int("SYNTHEX_PUBLIC_EXTRACTS_PER_USER_DAY", 3, maximum=100),
        extracts_global_day=_positive_int("SYNTHEX_PUBLIC_EXTRACTS_GLOBAL_DAY", 30, maximum=10000),
        searches_per_user_day=_positive_int("SYNTHEX_PUBLIC_SEARCHES_PER_USER_DAY", 10, maximum=1000),
        searches_global_day=_positive_int("SYNTHEX_PUBLIC_SEARCHES_GLOBAL_DAY", 100, maximum=100000),
    )


def validate_public_uploads(files: list, limits: PublicLimits) -> None:
    if len(files) > limits.max_batch:
        raise ValueError(f"Select at most {limits.max_batch} PDFs per batch on this deployment.")
    for uploaded in files:
        if uploaded.size > limits.max_pdf_bytes:
            raise ValueError(
                f"{uploaded.name} exceeds the {limits.max_pdf_bytes // (1024 * 1024)} MB upload limit."
            )


class PublicUsageLedger:
    """Atomically reserve per-user and deployment-wide daily provider actions."""

    def __init__(self, data_root: str | Path):
        self.log = JsonlLog(Path(data_root) / "usage" / "events.jsonl")

    def reserve(self, *, owner_key: str, action: str, per_user_limit: int, global_limit: int) -> bool:
        if not owner_key or action not in {"extract", "search"}:
            raise ValueError("A user and supported action are required")
        if per_user_limit < 1 or global_limit < 1:
            raise ValueError("Provider action limits must be positive")
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()

        def build(rows: list[dict]) -> dict | None:
            today = [row for row in rows if row.get("day") == day and row.get("action") == action]
            if len(today) >= global_limit or sum(row.get("owner_key") == owner_key for row in today) >= per_user_limit:
                return None
            return {
                "event_id": uuid4().hex,
                "day": day,
                "at": now.isoformat(),
                "owner_key": owner_key,
                "action": action,
            }

        return self.log.transact(build) is not None
