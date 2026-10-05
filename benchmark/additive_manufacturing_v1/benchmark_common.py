"""Shared locked-source and evidence helpers for AM V1 deterministic cases."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from synthex_platform.core.models import Evidence, Measurement


CASE_DIR = Path(__file__).resolve().parent


def load_locked(lock_name: str) -> tuple[Path, dict, dict]:
    lock = json.loads((CASE_DIR / lock_name).read_text(encoding="utf-8"))
    source = CASE_DIR / lock["source_file"]
    gold_path = CASE_DIR / lock["gold_file"]
    if sha256(source.read_bytes()).hexdigest() != lock["source_sha256"]:
        raise ValueError(f'{lock["case_id"]} source checksum differs from lock')
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError(f'{lock["case_id"]} gold checksum differs from lock')
    return source, json.loads(gold_path.read_text(encoding="utf-8")), lock


def table_evidence(page: int, table: str, row: str, column: str, snippet: str) -> Evidence:
    return Evidence(
        page=page,
        source_type="table",
        original_source_type="table_reported",
        verbatim_match=True,
        table_id=table,
        text_snippet=snippet,
        locator=f"row={row};column={column}",
    )


def text_evidence(page: int, section: str, snippet: str) -> Evidence:
    return Evidence(
        page=page,
        section=section,
        source_type="text",
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=snippet,
        locator=f"page={page};section={section}",
    )


def measurement(
    property_name: str,
    raw: str,
    value,
    unit: str | None,
    evidence: Evidence,
    *,
    scientific_type: str,
    qualifier: str = "exact",
    conditions: dict | None = None,
    uncertainty: float | None = None,
) -> Measurement:
    metadata = {"scientific_type": scientific_type, "data_kind": "scalar"}
    metadata.update(conditions or {})
    return Measurement(
        property=property_name,
        raw_value=raw,
        value=value,
        unit=unit,
        qualifier=qualifier,
        uncertainty=uncertainty,
        uncertainty_unit=unit if uncertainty is not None else None,
        conditions=metadata,
        evidence=[evidence],
    )
