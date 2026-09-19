from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

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
_TEMPERATURE_TOKEN = re.compile(r"([−–—-]?\s*\d+(?:\.\d+)?)\s*(?:°|◦)\s*C", re.IGNORECASE)
_C_RATE_TOKEN = re.compile(r"(?:\bC\s*/\s*(\d+(?:\.\d+)?)\b|([-+]?\d+(?:\.\d+)?)\s*C\b)", re.IGNORECASE)


@dataclass(frozen=True)
class _AxisValue:
    property: str
    raw_value: str
    value: float
    unit: str | None
    cell: TableCell


@dataclass(frozen=True)
class _MatrixCell:
    row_axis: _AxisValue
    column_axis: _AxisValue
    result_cell: TableCell
    value: float


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
            cell_numbers = _numeric_values(text)
            raw_numbers = _numeric_values(raw_value)
            if cell_numbers or raw_numbers:
                if len(cell_numbers) == len(raw_numbers) == 1 and math.isclose(
                    cell_numbers[0], raw_numbers[0], rel_tol=0.0,
                    abs_tol=max(1e-9, abs(raw_numbers[0]) * 1e-9),
                ):
                    return True
            else:
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
    property_key = re.sub(r"[^a-z0-9]+", "", condition.property.casefold())
    aliases = {
        "stateofcharge": ("soc", "state of charge"),
        "depthofdischarge": ("dod", "depth of discharge"),
        "crate": ("rate",),
        "cycle": ("cycle",),
        "currentdensity": ("current density",),
    }.get(property_key, ())
    if aliases:
        header_by_column = {
            column: " ".join(
                cell.raw_text or cell.text or ""
                for cell in table.cells
                if cell.column == column and cell.row < result_cell.row
            )
            for column in range(result_cell.column)
        }
        axis_columns = [
            column for column, text in header_by_column.items()
            if any(alias in _norm(text) for alias in aliases)
        ]
        if axis_columns:
            nearest_column = max(axis_columns)
            return [
                cell for cell in matches
                if cell.row == result_cell.row and cell.column == nearest_column
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
    conditions = list(point.additional_conditions)
    if point.temperature is not None:
        conditions.append(BatteryCondition(
            property="temperature",
            raw_value=point.temperature.raw_value,
            value=point.temperature.value,
            unit=point.temperature.unit,
            qualifier=point.temperature.qualifier,
        ))
    if point.c_rate:
        c_rate_value = _parse_c_rate(point.c_rate)
        conditions.append(BatteryCondition(
            property="C_rate",
            raw_value=point.c_rate,
            value=c_rate_value,
            unit="C" if c_rate_value is not None else None,
            qualifier="exact",
        ))
    if not conditions:
        return candidates
    viable: list[TableCell] = []
    for cell in candidates:
        if all(_axis_cells(table, cell, condition) for condition in conditions):
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
        confidence=cell.provenance.confidence or table.extraction_confidence,
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


def _parse_c_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _C_RATE_TOKEN.fullmatch(raw.strip())
    if not match:
        return None
    if match.group(1):
        denominator = float(match.group(1))
        return 1.0 / denominator if denominator else None
    return float(match.group(2))


def _single_number(raw: str | None) -> float | None:
    values = _numeric_values(raw)
    return values[0] if len(values) == 1 else None


def _axis_semantics(text: str) -> list[tuple[str, str | None]]:
    normalized = _norm(text)
    compact = re.sub(r"[^a-z0-9%]+", " ", normalized).strip()
    semantics: list[tuple[str, str | None]] = []

    def add(value: tuple[str, str | None]) -> None:
        if value not in semantics:
            semantics.append(value)

    if re.search(r"\bsoc\b", compact) or "state of charge" in compact:
        add(("state_of_charge", "%"))
    if re.search(r"\bdod\b", compact) or "depth of discharge" in compact:
        add(("depth_of_discharge", "%"))
    if "temperature" in compact or "°c" in normalized or "◦c" in normalized:
        add(("temperature", "°C"))
    if "current density" in compact:
        add(("current_density", None))
    if "concentration" in compact:
        add(("concentration", None))
    if "pressure" in compact:
        add(("pressure", None))
    if "composition" in compact:
        add(("composition", None))
    if "cycle" in compact:
        add(("cycle", None))
    if "rate" in compact and re.search(r"(?:^|\s)c(?:\s|$)", compact):
        add(("C_rate", "C"))
    return semantics


def _parse_axis_scalar(raw: str | None, property_name: str) -> float | None:
    if not raw:
        return None
    if property_name in {"state_of_charge", "depth_of_discharge"}:
        if "%" not in raw:
            return None
        return _single_number(raw)
    if property_name == "temperature":
        match = _TEMPERATURE_TOKEN.fullmatch(raw.strip())
        return _parse_temperature(match.group(1)) if match else None
    if property_name == "C_rate":
        parsed = _parse_c_rate(raw)
        return parsed if parsed is not None else _single_number(raw)
    return _single_number(raw)


def _cells_by_coordinate(table: TableRecord) -> dict[tuple[int, int], TableCell]:
    return {(cell.row, cell.column): cell for cell in table.cells}


def _row_axis(table: TableRecord) -> tuple[str, str | None, int, int, list[tuple[int, _AxisValue]]] | None:
    if not table.cells:
        return None
    cells = _cells_by_coordinate(table)
    rows = sorted({cell.row for cell in table.cells})
    columns = sorted({cell.column for cell in table.cells})
    candidates: list[tuple[int, int, str, str | None, list[tuple[int, _AxisValue]]]] = []
    for column in columns:
        for header_row in rows[:-1]:
            header_cell = cells.get((header_row, column))
            if header_cell is None:
                continue
            header_text = header_cell.raw_text or header_cell.text or ""
            for property_name, unit in _axis_semantics(header_text):
                values: list[tuple[int, _AxisValue]] = []
                for row in rows:
                    if row <= header_row:
                        continue
                    cell = cells.get((row, column))
                    if cell is None:
                        continue
                    raw = cell.raw_text or cell.text or ""
                    value = _parse_axis_scalar(raw, property_name)
                    if value is not None:
                        values.append((row, _AxisValue(property_name, raw, value, unit, cell)))
                if len(values) >= 2:
                    candidates.append((len(values), -column, property_name, unit, values))
    if not candidates:
        return None
    _, neg_column, property_name, unit, values = max(candidates, key=lambda item: (item[0], item[1]))
    return property_name, unit, -neg_column, min(row for row, _ in values), values


def _page_for_table(bundle: SourceBundle, table: TableRecord):
    return next((page for page in bundle.pages if page.page == table.page), None)


def _temperature_header_from_page(
    bundle: SourceBundle,
    table: TableRecord,
    expected: int,
) -> list[tuple[str, float]]:
    page = _page_for_table(bundle, table)
    if page is None:
        return []
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    caption_indexes = [
        index for index, line in enumerate(lines)
        if (
            table.table_number
            and re.match(rf"^Table\s+{re.escape(table.table_number)}\b", line, re.IGNORECASE)
        ) or (table.caption and _norm(line) == _norm(table.caption))
    ]
    for caption_index in caption_indexes:
        for line in lines[caption_index + 1:caption_index + 5]:
            matches = list(_TEMPERATURE_TOKEN.finditer(line))
            if len(matches) == expected:
                return [
                    (match.group(0), _parse_temperature(match.group(1)))
                    for match in matches
                ]
    return []


def _column_axis_values(
    bundle: SourceBundle,
    table: TableRecord,
    *,
    row_property: str,
    first_data_row: int,
    data_columns: list[int],
) -> list[_AxisValue]:
    header_cells: list[TableCell] = []
    for column in data_columns:
        candidates = [
            cell for cell in table.cells
            if cell.column == column and cell.row < first_data_row
        ]
        if not candidates:
            return []
        header_cells.append(max(candidates, key=lambda cell: cell.row))

    header_context = " ".join(
        [table.caption or ""]
        + [cell.raw_text or cell.text or "" for cell in header_cells]
    )
    semantics_options = [
        semantics for semantics in _axis_semantics(header_context)
        if semantics[0] != row_property
    ]
    for property_name, unit in semantics_options:
        direct: list[_AxisValue] = []
        for cell in header_cells:
            raw = cell.raw_text or cell.text or ""
            value = _parse_axis_scalar(raw, property_name)
            if value is None:
                direct = []
                break
            direct.append(_AxisValue(property_name, raw, value, unit, cell))
        if len(direct) == len(data_columns) and len({item.value for item in direct}) == len(direct):
            return direct

        if property_name == "temperature":
            repaired = _temperature_header_from_page(bundle, table, len(data_columns))
            if repaired and len({value for _, value in repaired}) == len(repaired):
                return [
                    _AxisValue(property_name, raw, value, unit, cell)
                    for (raw, value), cell in zip(repaired, header_cells)
                ]
    return []


def _matrix_cells(bundle: SourceBundle, table: TableRecord) -> list[_MatrixCell]:
    row_axis = _row_axis(table)
    if row_axis is None:
        return []
    row_property, _, row_column, first_data_row, row_values = row_axis
    cells = _cells_by_coordinate(table)
    rows = [row for row, _ in row_values]
    columns = sorted({cell.column for cell in table.cells if cell.column != row_column})
    data_columns = [
        column for column in columns
        if all(
            (row, column) in cells
            and _single_number(cells[(row, column)].raw_text or cells[(row, column)].text) is not None
            for row in rows
        )
    ]
    if len(data_columns) < 2:
        return []
    column_values = _column_axis_values(
        bundle,
        table,
        row_property=row_property,
        first_data_row=first_data_row,
        data_columns=data_columns,
    )
    if len(column_values) != len(data_columns):
        return []
    row_by_number = dict(row_values)
    column_by_number = dict(zip(data_columns, column_values))
    matrix: list[_MatrixCell] = []
    for row in rows:
        for column in data_columns:
            result_cell = cells[(row, column)]
            value = _single_number(result_cell.raw_text or result_cell.text)
            if value is None:
                return []
            matrix.append(_MatrixCell(row_by_number[row], column_by_number[column], result_cell, value))
    return matrix


def _point_references_table(point: BatteryPerformancePoint, table: TableRecord, bundle: SourceBundle) -> bool:
    page_tables = [candidate for candidate in bundle.tables if candidate.page == table.page]
    for evidence in point.evidence:
        if evidence.source_type != "table" or evidence.page not in (None, table.page):
            continue
        if evidence.table_id and _table_ref_matches(evidence.table_id, table):
            return True
        if evidence.text_snippet and table.caption and _norm(evidence.text_snippet) == _norm(table.caption):
            return True
        if not evidence.table_id and len(page_tables) == 1:
            return True
    return False


def _common_value(values):
    present = [value for value in values if value not in (None, "")]
    return present[0] if present and all(value == present[0] for value in present) else None


def _point_axis_value(point: BatteryPerformancePoint, property_name: str) -> float | None:
    if property_name == "temperature" and point.temperature and point.temperature.value is not None:
        return float(point.temperature.value)
    for condition in point.additional_conditions:
        if condition.property == property_name and condition.value is not None:
            return float(condition.value)
    return None


def _matrix_key(cell: _MatrixCell) -> tuple[str, float, str, float]:
    return (
        cell.row_axis.property,
        float(cell.row_axis.value),
        cell.column_axis.property,
        float(cell.column_axis.value),
    )


def _matching_matrix_cells(point: BatteryPerformancePoint, matrix: list[_MatrixCell]) -> list[_MatrixCell]:
    if point.value is None:
        return []
    candidates = [
        cell for cell in matrix
        if math.isclose(float(point.value), cell.value, rel_tol=0.0, abs_tol=max(1e-9, abs(cell.value) * 1e-9))
    ]
    for property_name in {cell.row_axis.property for cell in matrix} | {cell.column_axis.property for cell in matrix}:
        expected = _point_axis_value(point, property_name)
        if expected is None:
            continue
        candidates = [
            cell for cell in candidates
            if math.isclose(
                expected,
                cell.row_axis.value if cell.row_axis.property == property_name else cell.column_axis.value,
                rel_tol=0.0,
                abs_tol=max(1e-9, abs(expected) * 1e-9),
            )
        ]
    return candidates


def _upsert_axis_condition(point: BatteryPerformancePoint, axis: _AxisValue, table: TableRecord) -> None:
    evidence = _cell_evidence(table, axis.cell)
    condition = next(
        (item for item in point.additional_conditions if item.property == axis.property),
        None,
    )
    if condition is None:
        condition = BatteryCondition(
            property=axis.property,
            raw_value=axis.raw_value,
            value=axis.value,
            unit=axis.unit,
            qualifier="exact",
            evidence=[],
        )
        point.additional_conditions.append(condition)
    else:
        condition.raw_value = axis.raw_value
        condition.value = axis.value
        condition.unit = axis.unit
        condition.qualifier = "exact"
    _append_unique_evidence(condition.evidence, evidence)
    if axis.property == "temperature":
        point.temperature = BatteryQuantity(
            raw_value=axis.raw_value,
            value=axis.value,
            unit=axis.unit,
            qualifier="exact",
        )


def _protocol_condition_evidence(
    bundle: SourceBundle,
    table: TableRecord,
    raw_value: str | None,
) -> BatteryEvidence | None:
    if not raw_value or not table.table_number:
        return None
    page = _page_for_table(bundle, table)
    if page is None:
        return None
    text = page.text
    caption_matches = list(re.finditer(
        rf"Table\s+{re.escape(table.table_number)}\b",
        text,
        flags=re.IGNORECASE,
    ))
    raw_normalized = _norm(raw_value)
    for caption_match in caption_matches:
        start = max(0, caption_match.start() - 2000)
        window = text[start:caption_match.start()]
        if f"table {table.table_number}" not in _norm(window):
            continue
        segments = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n", window) if segment.strip()]
        supported = [segment for segment in segments if raw_normalized in _norm(segment)]
        if supported:
            return BatteryEvidence(
                page=table.page,
                section=table.caption or f"Table {table.table_number}",
                text_snippet=supported[-1],
                source_type="text",
                original_source_type=page.origin,
                confidence=table.extraction_confidence,
            )
    return None


def _add_protocol_condition(
    point: BatteryPerformancePoint,
    raw_value: str | None,
    evidence: BatteryEvidence | None,
) -> None:
    value = _parse_c_rate(raw_value)
    if raw_value is None or value is None or evidence is None:
        return
    condition = next(
        (item for item in point.additional_conditions if item.property in {"C_rate", "c_rate"}),
        None,
    )
    if condition is None:
        condition = BatteryCondition(
            property="C_rate",
            raw_value=raw_value,
            value=value,
            unit="C",
            qualifier="exact",
            evidence=[],
        )
        point.additional_conditions.append(condition)
    _append_unique_evidence(condition.evidence, evidence.model_copy(deep=True))
    point.c_rate = raw_value


def recover_dense_battery_matrices(doc: BatteryDocument, bundle: SourceBundle | None) -> BatteryDocument:
    """Expand source-backed two-dimensional battery tables from their parsed cells.

    The language-model output is used only to bind a parsed table to a battery group and to supply
    result semantics such as property and unit. Every numerical observation and matrix coordinate is
    enumerated deterministically from the rectangular ``TableRecord``. Ambiguous table/group/property
    bindings are left untouched so the ordinary admission gate can quarantine unsupported candidates.
    """
    if bundle is None or not bundle.tables:
        return doc

    for table in bundle.tables:
        matrix = _matrix_cells(bundle, table)
        if not matrix:
            continue

        matching_groups = []
        for group in doc.battery_groups:
            seeds = [
                point for point in group.performance_points
                if _point_references_table(point, table, bundle)
            ]
            if seeds:
                matching_groups.append((group, seeds))
        if len(matching_groups) != 1:
            continue

        group, table_seeds = matching_groups[0]
        properties = {point.property for point in table_seeds if point.property}
        units = {point.unit for point in table_seeds if point.unit}
        if len(properties) != 1 or len(units) != 1:
            continue
        property_name = next(iter(properties))
        unit = next(iter(units))
        seeds = [point for point in table_seeds if point.property == property_name]
        if not seeds:
            continue

        method = _common_value(point.method for point in seeds)
        c_rate = _common_value(point.c_rate for point in seeds)
        c_rate_evidence = _protocol_condition_evidence(bundle, table, c_rate)
        voltage_window = _common_value(point.voltage_window for point in seeds)
        cycle = _common_value(point.cycle for point in seeds)
        explicit_ownership = _common_value(
            point.ownership for point in seeds if point.ownership != "unknown"
        )
        ownership = explicit_ownership or group.ownership

        existing: dict[tuple[str, float, str, float], BatteryPerformancePoint] = {}
        for point in seeds:
            candidates = _matching_matrix_cells(point, matrix)
            if len(candidates) == 1:
                existing.setdefault(_matrix_key(candidates[0]), point)

        for matrix_cell in matrix:
            key = _matrix_key(matrix_cell)
            point = existing.get(key)
            if point is None:
                result_raw = matrix_cell.result_cell.raw_text or matrix_cell.result_cell.text or f"{matrix_cell.value:g}"
                point = BatteryPerformancePoint(
                    property=property_name,
                    raw_value=f"{result_raw} {unit}".strip(),
                    value=matrix_cell.value,
                    unit=unit,
                    qualifier="exact",
                    cycle=cycle,
                    c_rate=c_rate if c_rate_evidence is not None else None,
                    voltage_window=voltage_window,
                    method=method,
                    ownership=ownership,
                    evidence=[],
                )
                group.performance_points.append(point)
                existing[key] = point
            else:
                point.method = point.method or method
                point.voltage_window = point.voltage_window or voltage_window
                point.cycle = point.cycle if point.cycle is not None else cycle
                if point.ownership == "unknown":
                    point.ownership = ownership

            _append_unique_evidence(point.evidence, _cell_evidence(table, matrix_cell.result_cell))
            _upsert_axis_condition(point, matrix_cell.row_axis, table)
            _upsert_axis_condition(point, matrix_cell.column_axis, table)
            _add_protocol_condition(point, c_rate, c_rate_evidence)

        row_values = {cell.row_axis.value for cell in matrix}
        column_values = {cell.column_axis.value for cell in matrix}
        note = (
            f"Deterministic structured-table recovery preserved {len(matrix)} {property_name} "
            f"observations from {table.table_id} across {len(row_values)} "
            f"{matrix[0].row_axis.property} values and {len(column_values)} "
            f"{matrix[0].column_axis.property} values."
        )
        if note not in doc.extraction_notes:
            doc.extraction_notes.append(note)

    return doc


def enrich_table_condition_evidence(doc: BatteryDocument, bundle: SourceBundle | None) -> BatteryDocument:
    """Recover source-backed row/column evidence for multidimensional battery tables."""
    doc = recover_dense_battery_matrices(doc, bundle)
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
