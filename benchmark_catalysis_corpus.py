"""Offline corpus integrity and routing utilities for Catalysis V1 Stage 3."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any


REQUIRED_BENCHMARK_ROLES = (
    "heterogeneous_experimental_gold",
    "co2rr_electrocatalysis_gold",
    "computational_dft",
    "stability_deactivation",
    "review_contamination",
    "deferred_photocatalysis",
    "cross_domain_negative_control",
)

REQUIRED_ENTRY_FIELDS = (
    "benchmark_id", "filename", "title", "doi", "year", "expected_route",
    "expected_subtypes", "expected_ownership_behavior", "expected_scope_status",
    "checksum", "benchmark_role", "licensing_source_note",
)


def _safe_path(path: Path) -> Path:
    resolved = path.resolve()
    if os.name == "nt" and not str(resolved).startswith("\\\\?\\"):
        return Path("\\\\?\\" + str(resolved))
    return resolved


def file_sha256(path: Path) -> str:
    digest = sha256()
    with _safe_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(
    manifest: dict[str, Any],
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate the seven-role manifest and optionally verify local bytes/checksums."""
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        return {
            "valid": False,
            "entry_count": 0,
            "missing_roles": list(REQUIRED_BENCHMARK_ROLES),
            "errors": ["entries must be a list"],
        }

    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    seen_roles: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {index} is not an object")
            continue
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry or entry.get(field) in (None, ""):
                errors.append(f"entry {index} missing required field: {field}")
        benchmark_id = entry.get("benchmark_id")
        filename = entry.get("filename")
        role = entry.get("benchmark_role")
        if benchmark_id in seen_ids:
            errors.append(f"duplicate benchmark_id: {benchmark_id}")
        if filename in seen_files:
            errors.append(f"duplicate filename: {filename}")
        if role in seen_roles:
            errors.append(f"duplicate benchmark_role: {role}")
        if benchmark_id:
            seen_ids.add(benchmark_id)
        if filename:
            seen_files.add(filename)
        if role:
            seen_roles.add(role)
        checksum = str(entry.get("checksum") or "")
        if checksum and (len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.casefold())):
            errors.append(f"entry {index} checksum is not SHA-256")
        if corpus_dir is not None and filename:
            path = corpus_dir / filename
            try:
                actual_checksum = file_sha256(path)
            except OSError as exc:
                errors.append(f"entry {index} PDF unavailable: {filename} ({exc})")
            else:
                if actual_checksum.casefold() != checksum.casefold():
                    errors.append(f"entry {index} checksum mismatch: {filename}")

    missing_roles = [role for role in REQUIRED_BENCHMARK_ROLES if role not in seen_roles]
    extra_roles = sorted(seen_roles - set(REQUIRED_BENCHMARK_ROLES))
    if missing_roles:
        errors.append("missing benchmark roles: " + ", ".join(missing_roles))
    if extra_roles:
        errors.append("unexpected benchmark roles: " + ", ".join(extra_roles))
    if len(entries) != len(REQUIRED_BENCHMARK_ROLES):
        errors.append(f"expected exactly {len(REQUIRED_BENCHMARK_ROLES)} entries")
    return {
        "valid": not errors,
        "entry_count": len(entries),
        "missing_roles": missing_roles,
        "errors": errors,
    }


def identify_missing_categories(manifest: dict[str, Any]) -> list[str]:
    present = {
        entry.get("benchmark_role")
        for entry in manifest.get("entries", [])
        if isinstance(entry, dict) and entry.get("benchmark_role")
    }
    return [role for role in REQUIRED_BENCHMARK_ROLES if role not in present]


def main() -> None:
    benchmark_root = Path(__file__).resolve().parent / "benchmark" / "catalysis_v1"
    manifest = json.loads((benchmark_root / "corpus_manifest.json").read_text(encoding="utf-8"))
    result = validate_manifest(manifest, benchmark_root / "corpus_pdfs")
    print(json.dumps({"manifest_status": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
