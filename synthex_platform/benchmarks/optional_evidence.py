"""Verify local provider evidence without making it a scientific replay prerequisite."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from .provider_artifacts import _io_path


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def inspect_optional_raw_artifact(
    repository_root: Path, relative_path: str, expected_sha256: str
) -> dict[str, object]:
    """Distinguish an absent historical body from a present but corrupt one.

    The caller supplies only committed metadata. Missing local evidence is not a
    zero score or a scientific failure; a present body must match its recorded
    digest. Paths are confined to the current checkout.
    """
    root = repository_root.resolve()
    relative = Path(relative_path)
    if relative.is_absolute() or not relative_path or ".." in relative.parts:
        raise ValueError("Provider artifact path must be repository-relative")
    if not _SHA256.fullmatch(expected_sha256):
        raise ValueError("Provider artifact requires a recorded SHA-256 digest")
    artifact = (root / relative).resolve()
    if not artifact.is_relative_to(root):
        raise ValueError("Provider artifact escapes repository")
    readable = _io_path(artifact)
    if not readable.is_file():
        return {"RAW_PROVIDER_ARTIFACT_AVAILABLE": False,
                "integrity": "NOT_AVAILABLE_LOCALLY"}
    if sha256(readable.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Provider artifact SHA-256 mismatch")
    return {"RAW_PROVIDER_ARTIFACT_AVAILABLE": True, "integrity": "VERIFIED"}
