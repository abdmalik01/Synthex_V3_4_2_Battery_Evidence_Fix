from __future__ import annotations

import math
import re
from collections.abc import Iterable

from synthex_platform.visual.models import TableCell, TableRecord

from .battery_evidence import normalize_evidence_text
from .battery_models import BatteryCondition, BatteryDocument, BatteryEvidence
from .source_context import SourceBundle


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _norm(value: str | None) -> str:
    return normalize_evidence_text(value or "")


def _numeric_values(value: str | None) -> list[float]:
    if not value:
        return []
    out: list[float] = []
    for token in _NUMBER.findall(_norm(value)):
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def _cell_matches(cell: TableCell, raw_value: str | None, value: float | None) -> bool:
    text = cell.raw_text or cell.text or ""
    normalized_cell = _norm(text)
    normalized_raw = _norm(raw_value)
    if normalized_raw and normalized_cell:
        if normalized_raw == normalized_cell:
            return True
        if normalized_raw in normalized_cell or normalized_cell in normalized_raw:
            if len(_numeric_values(text)) <= 1:
                return True
    if value is None:
        return False
    numbers = _numeric_values(text)
    if len(numbers) != 1:
        return False
    return math.isclose(numbers[0], float(value), rel_tol=0.0, abs_tol=max(1e-9, abs(float(value)) * 1e-9))


def _table_ref_matches(reference: str | None, table: TableRecord) -> bool:
    if not reference:
        return False
    ref = re.sub(r"[^a-z0-9]+", "", reference.casefold())
    candidates = {
        re.sub(r"[^a-z0-9]+", "", (table.table_id or "").casefold()),
        re.sub(r"[^a-z0-9]+", "", (table.table_number or "").casefold()),
        re.sub(r"[^a-z0-9]+", "", (f"Table {table.table_number}" if table.table_number else "").casefold()),
    }
    caption = re.sub(r"[^a-z0-9]+", "", (table.caption or "").casefold())
    if ref in candidates:
        return True
    return bool(caption and ref and caption.startswith(ref))


def _candidate_tables(bundle: SourceBundle, evidence: BatteryEvidence) -> list[TableRecord]:
    page_tables = [table for table in bundle.tables if evidence.page is None or table.page == evidence.page]
    if evidence.table_id:
        matched = [table for table in page_tables if _table_ref_matches(evidence.table_id, table)]
        if matched:
            return matched
    return page_tables if len(page_tables) == 1 else []


def _axis_cells(table: TableRecord, result_cell: TableCell, condition: BatteryCondition) -> list[TableCell]:
    matches = [
        cell for cell in table.cells
        if _cell_matches(cell, condition.raw_value, condition.value)
    ]
    return [
        cell for cell in matches
        if (
            cell.row == result_cell.row and cell.column < result_cell.column
        ) or (
            cell.column == result_cell.column and cell.row < result_cell.row
        )
    ]


def _result_cells(table: TableRecord, point) -> list[TableCell]:
    candidates = [
        cell for cell in table.cells
        if _cell_matches(cell, point.raw_value, point.value)
    ]
    if not point.additional_conditions:
        return candidates
    viable: list[TableCell] = []
    for cell in candidates:
        if all(_axis_cells(table, cell, condition) for condition in point.additional_conditions):
            viable.append(cell)
    return viable


def _cell_evidence(table: TableRecord, cell: TableCell) -> BatteryEvidence:
    section = table.caption or (f"Table {table.table_number}" if table.table_number else None)
    return BatteryEvidence(
        page=table.page,
        section=section,
        text_snippet=cell.raw_text or cell.text,
        source_type="table",
        original_source_type="table_reported",
        table_id=table.table_id,
        locator=f"row={cell.row};column={cell.column};cell_id={cell.cell_id}",
        confidence=table.extraction_confidence,
    )


def _dedupe_cells(cells: Iterable[TableCell]) -> list[TableCell]:
    out: list[TableCell] = []
    seen: set[tuple[int, int, str | None]] = set()
    for cell in cells:
        key = (cell.row, cell.column, cell.cell_id)
        if key not in seen:
            seen.add(key)
            out.append(cell)
    return out


def _append_unique_evidence(target: list[BatteryEvidence], evidence: BatteryEvidence) -> None:
    key = (evidence.table_id, evidence.locator, evidence.text_snippet)
    if any((item.table_id, item.locator, item.text_snippet) == key for item in target):
        return
    target.append(evidence)


def enrich_table_condition_evidence(doc: BatteryDocument, bundle: SourceBundle | None) -> BatteryDocument:
    """Recover source-backed row/column evidence for multidimensional battery tables.

    The LLM may preserve the correct scientific axes while emitting a synthetic row string such
    as ``100% | 14.69`` that is not a verbatim PDF substring. We therefore resolve the claim back
    to one native structured table cell. The result cell and any missing additional-condition axes
    receive independent cell-level evidence only when the complete condition set identifies one
    unambiguous matrix location.
    """
    if bundle is None or not bundle.tables:
        return doc

    for group in doc.battery_groups:
        for point in group.performance_points:
            missing = [condition for condition in point.additional_conditions if not condition.evidence]
            table_evidence = [item for item in point.evidence if item.source_type == "table"]
            if not table_evidence:
                continue

            resolved: list[tuple[TableRecord, TableCell]] = []
            for source_evidence in table_evidence:
                for table in _candidate_tables(bundle, source_evidence):
                    for cell in _result_cells(table, point):
                        resolved.append((table, cell))

            unique_results: dict[tuple[str, int, int], tuple[TableRecord, TableCell]] = {}
            for table, cell in resolved:
                unique_results[(table.table_id, cell.row, cell.column)] = (table, cell)
            if len(unique_results) != 1:
                continue

            table, result_cell = next(iter(unique_results.values()))

            # Preserve the original LLM evidence for audit, but add a native cell-level
            # evidence object whose text is exactly the source cell and whose locator is stable.
            _append_unique_evidence(point.evidence, _cell_evidence(table, result_cell))

            for source_evidence in table_evidence:
                if source_evidence.page == table.page and (
                    not source_evidence.table_id or _table_ref_matches(source_evidence.table_id, table)
                ):
                    source_evidence.table_id = table.table_id
                    source_evidence.original_source_type = source_evidence.original_source_type or "table_reported"
                    source_evidence.locator = source_evidence.locator or (
                        f"row={result_cell.row};column={result_cell.column};cell_id={result_cell.cell_id}"
                    )

            for condition in missing:
                cells = _dedupe_cells(_axis_cells(table, result_cell, condition))
                if len(cells) == 1:
                    _append_unique_evidence(condition.evidence, _cell_evidence(table, cells[0]))

    return doc
