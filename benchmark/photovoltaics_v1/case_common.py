"""Shared helpers for locked Photovoltaics V1 benchmark cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement


CASE_DIR = Path(__file__).resolve().parent


def read_json(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_locked(path: Path, expected: str, label: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{label} checksum differs from source lock: {actual}")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("ﬁ", "fi").replace("ﬃ", "ffi")).strip()


def text_evidence(page: int, snippet: str, *, section: str, source_type: str = "text") -> Evidence:
    return Evidence(
        page=page,
        section=section,
        source_type=source_type,
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=snippet,
        locator=f"page={page};section={section}",
    )


def canonical_digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_locked(lock_name: str) -> tuple[Path, dict, dict]:
    lock = read_json(lock_name)
    source = (CASE_DIR / lock["source_file"]).resolve()
    gold = read_json(lock["gold_file"])
    assert_locked(source, lock["source_sha256"], f"{gold['case_id']} source")
    assert_locked(CASE_DIR / lock["gold_file"], lock["gold_sha256"], f"{gold['case_id']} gold")
    return source, gold, lock


def table_evidence(
    *,
    page: int,
    table: str,
    row: str,
    column: str,
    snippet: str,
    source_sha256: str,
) -> Evidence:
    return Evidence(
        page=page,
        section=table,
        source_type="table",
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=snippet,
        table_id=stable_id("tbl", source_sha256, table, page),
        locator=f"page={page};table={table};row={row};column={column}",
    )


def measurement(
    property_name: str,
    raw_value: str,
    value: float,
    unit: str,
    evidence: Evidence,
    *,
    scientific_type: str,
    qualifier: str = "exact",
    conditions: dict | None = None,
) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=raw_value,
        value=value,
        unit=unit,
        qualifier=qualifier,
        conditions={
            "scientific_type": scientific_type,
            "data_kind": "scalar",
            **(conditions or {}),
        },
        evidence=[evidence],
    )
