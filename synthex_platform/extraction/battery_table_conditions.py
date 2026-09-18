from __future__ import annotations

import math
import re
from collections.abc import Iterable

from synthex_platform.visual.models import TableCell, TableRecord

from .battery_evidence import normalize_evidence_text
from .battery_models import (
    BatteryCondition,
    BatteryDocument,
    BatteryEvidence,
    BatteryPerformancePoint,
    BatteryQuantity,
)
from .source_context import SourceBundle


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_TABLE_LINE = re.compile(r"^\s*Table\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)
_SOC_ROW = re.compile(r"^\s*(\d+(?:\.\d+)?)%\s+(.+)$")
_TEMPERATURE_TOKEN = re.compile(r"([−–—-]?\s*\d+(?:\.\d+)?)\s*(?:°|◦)\s*C", re.IGNORECASE)


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


def _parse_temperature(raw: str) -> float:
    cleaned = raw.replace("−", "-").replace("–", "-").replace("—", "-").replace(" ", "")
    return float(cleaned)


def _table_number_from_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    match = re.search(r"table\s*(\d+[A-Za-z]?)", reference, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _matrix_existing_key(point: BatteryPerformancePoint) -> tuple[float, float] | None:
    soc = None
    temperature = point.temperature.value if point.temperature else None
    for condition in point.additional_conditions:
        if condition.property == "state_of_charge" and condition.value is not None:
            soc = float(condition.value)
        elif condition.property == "temperature" and condition.value is not None:
            temperature = float(condition.value)
    if soc is None or temperature is None:
        return None
    return float(soc), float(temperature)


def _text_table_evidence(
    *,
    page: int,
    section: str,
    table_id: str,
    text: str,
    row: int,
    column: int,
) -> BatteryEvidence:
    return BatteryEvidence(
        page=page,
        section=section,
        text_snippet=text,
        source_type="table",
        original_source_type="table_reported",
        table_id=table_id,
        locator=f"row={row};column={column}",
        confidence=1.0,
    )


def recover_dense_battery_matrices(doc: BatteryDocument, bundle: SourceBundle | None) -> BatteryDocument:
    """Deterministically recover explicit SOC x temperature resistance matrices.

    This path is intentionally narrow and source-driven. It only activates when the page contains an
    explicit Table caption describing resistance under both SOC and temperature, an explicit temperature
    header, and rectangular SOC rows. A pre-existing LLM-extracted internal-resistance point is required
    to supply the reported unit, so the deterministic layer never invents a unit or scientific property.
    """
    if bundle is None or not bundle.pages:
        return doc

    for page_context in bundle.pages:
        lines = [line.strip() for line in page_context.text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            table_match = _TABLE_LINE.match(line)
            lower = line.casefold()
            if not table_match or "resistance" not in lower or "temperature" not in lower or "soc" not in lower:
                continue
            table_number = table_match.group(1)
            header_index = None
            temperatures: list[float] = []
            header_line = None
            for probe in range(index + 1, min(index + 5, len(lines))):
                candidate = lines[probe]
                if "soc" not in candidate.casefold():
                    continue
                tokens = _TEMPERATURE_TOKEN.findall(candidate)
                if len(tokens) >= 2:
                    header_index = probe
                    header_line = candidate
                    temperatures = [_parse_temperature(token) for token in tokens]
                    break
            if header_index is None or header_line is None:
                continue

            matrix_rows: list[tuple[float, list[float], str]] = []
            for probe in range(header_index + 1, min(header_index + 40, len(lines))):
                row_line = lines[probe]
                row_match = _SOC_ROW.match(row_line)
                if not row_match:
                    if matrix_rows:
                        break
                    continue
                soc = float(row_match.group(1))
                values = [float(token) for token in _NUMBER.findall(row_match.group(2))]
                if len(values) != len(temperatures):
                    if matrix_rows:
                        break
                    continue
                matrix_rows.append((soc, values, row_line))
            if len(matrix_rows) < 2:
                continue

            matching_groups = []
            for group in doc.battery_groups:
                seeds = []
                for point in group.performance_points:
                    if point.property != "internal_resistance" or not point.unit:
                        continue
                    evidence_numbers = {
                        _table_number_from_reference(item.table_id)
                        for item in point.evidence
                        if item.page in (None, page_context.page)
                    }
                    if table_number in evidence_numbers:
                        seeds.append(point)
                if seeds:
                    matching_groups.append((group, seeds))
            if len(matching_groups) != 1:
                continue

            group, seeds = matching_groups[0]
            units = {point.unit for point in seeds if point.unit}
            if len(units) != 1:
                continue
            unit = next(iter(units))
            table_record = next(
                (
                    table for table in bundle.tables
                    if table.page == page_context.page and table.table_number == table_number
                ),
                None,
            )
            table_id = table_record.table_id if table_record else f"Table {table_number}"
            section = line
            existing = {
                key: point
                for point in group.performance_points
                if point.property == "internal_resistance"
                for key in [_matrix_existing_key(point)]
                if key is not None
            }

            for row_index, (soc, values, row_line) in enumerate(matrix_rows, start=1):
                soc_evidence = _text_table_evidence(
                    page=page_context.page, section=section, table_id=table_id,
                    text=row_line, row=row_index, column=0,
                )
                for column_index, (temperature, value) in enumerate(zip(temperatures, values), start=1):
                    result_evidence = _text_table_evidence(
                        page=page_context.page, section=section, table_id=table_id,
                        text=row_line, row=row_index, column=column_index,
                    )
                    temperature_evidence = _text_table_evidence(
                        page=page_context.page, section=section, table_id=table_id,
                        text=header_line, row=0, column=column_index,
                    )
                    key = (float(soc), float(temperature))
                    point = existing.get(key)
                    if point is None:
                        point = BatteryPerformancePoint(
                            property="internal_resistance",
                            raw_value=f"{value:g} {unit}",
                            value=value,
                            unit=unit,
                            qualifier="exact",
                            temperature=BatteryQuantity(
                                raw_value=f"{temperature:g} °C",
                                value=temperature,
                                unit="°C",
                                qualifier="exact",
                            ),
                            additional_conditions=[
                                BatteryCondition(
                                    property="state_of_charge",
                                    raw_value=f"{soc:g}%",
                                    value=soc,
                                    unit="%",
                                    qualifier="exact",
                                    evidence=[soc_evidence],
                                ),
                                BatteryCondition(
                                    property="temperature",
                                    raw_value=f"{temperature:g} °C",
                                    value=temperature,
                                    unit="°C",
                                    qualifier="exact",
                                    evidence=[temperature_evidence],
                                ),
                            ],
                            ownership="focal_work",
                            evidence=[result_evidence],
                        )
                        group.performance_points.append(point)
                        existing[key] = point
                    else:
                        _append_unique_evidence(point.evidence, result_evidence)
                        soc_condition = next(
                            (condition for condition in point.additional_conditions if condition.property == "state_of_charge"),
                            None,
                        )
                        if soc_condition is None:
                            soc_condition = BatteryCondition(
                                property="state_of_charge", raw_value=f"{soc:g}%", value=soc,
                                unit="%", qualifier="exact", evidence=[],
                            )
                            point.additional_conditions.append(soc_condition)
                        _append_unique_evidence(soc_condition.evidence, soc_evidence)
                        temp_condition = next(
                            (condition for condition in point.additional_conditions if condition.property == "temperature"),
                            None,
                        )
                        if temp_condition is None:
                            temp_condition = BatteryCondition(
                                property="temperature", raw_value=f"{temperature:g} °C", value=temperature,
                                unit="°C", qualifier="exact", evidence=[],
                            )
                            point.additional_conditions.append(temp_condition)
                        _append_unique_evidence(temp_condition.evidence, temperature_evidence)
                        if point.temperature is None:
                            point.temperature = BatteryQuantity(
                                raw_value=f"{temperature:g} °C", value=temperature,
                                unit="°C", qualifier="exact",
                            )

            doc.extraction_notes.append(
                f"Deterministic structured-table recovery preserved {len(matrix_rows) * len(temperatures)} "
                f"internal-resistance observations from Table {table_number} across "
                f"{len(matrix_rows)} SOC levels and {len(temperatures)} temperatures."
            )

    return doc


def enrich_table_condition_evidence(doc: BatteryDocument, bundle: SourceBundle | None) -> BatteryDocument:
    """Recover source-backed row/column evidence for multidimensional battery tables."""
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
