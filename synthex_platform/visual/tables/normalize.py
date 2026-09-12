"""Conservative table normalization that never mutates raw extraction."""

from __future__ import annotations

import re
from typing import Any


_UNIT_IN_HEADER = re.compile(r"(?:\(([^()]+)\)|\[([^\[\]]+)\])\s*$")


def _structural_text(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact or None


def normalize_table(
    raw_grid: list[list[str | None]], headers: list[list[str | None]],
) -> dict[str, Any]:
    """Produce a separately stored, low-risk convenience representation."""
    cleaned_headers = [[_structural_text(cell) for cell in row] for row in headers]
    cleaned_rows = [[_structural_text(cell) for cell in row] for row in raw_grid]
    result: dict[str, Any] = {
        "status": "partial",
        "headers": cleaned_headers,
        "rows": cleaned_rows,
        "row_mappings": [],
    }
    if len(cleaned_headers) != 1 or not cleaned_headers[0] or any(cell is None for cell in cleaned_headers[0]):
        result["reason"] = "header_structure_ambiguous"
        return result
    header = cleaned_headers[0]
    if len(set(header)) != len(header):
        result["reason"] = "header_names_not_unique"
        return result
    mappings = []
    for row in cleaned_rows:
        if len(row) != len(header):
            result["reason"] = "row_width_differs_from_header"
            return result
        mappings.append(dict(zip(header, row)))
    result.update(status="normalized", row_mappings=mappings)
    return result


def column_units(headers: list[list[str | None]]) -> dict[str, str]:
    """Extract explicitly bracketed header units only; never infer or convert."""
    if len(headers) != 1:
        return {}
    units: dict[str, str] = {}
    for header in headers[0]:
        if not header:
            continue
        match = _UNIT_IN_HEADER.search(header.strip())
        if match:
            unit = (match.group(1) or match.group(2) or "").strip()
            if unit:
                units[header] = unit
    return units
