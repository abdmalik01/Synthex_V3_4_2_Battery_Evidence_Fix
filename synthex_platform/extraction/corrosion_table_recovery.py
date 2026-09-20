"""Deterministic recovery of source-reported corrosion parameter tables.

This module only augments EIS experiment scaffolds that already have an explicit,
source-extracted exposure-time association. It never creates samples, treatments,
environments, or experiments and never interprets figure pixels as numeric data.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .corrosion_models import CorrosionDocument, CorrosionEvidence, CorrosionMetric, CorrosionQuantity
from .source_context import SourceBundle


_TABLE_CAPTION = re.compile(r"^\s*(Table\s+\d+[A-Za-z]?)\s*[.:\-]", re.IGNORECASE)
_HEADER_TOKEN = re.compile(
    r"\bTime\b|\bR\s*(?:coat|pore|cp|ct|ox|e|s|t|f)\b|"
    r"\bC\s*(?:dl|cp|coat)\b|\bQ\b|\bY\s*0\b|\bn\s*(?:dl|cp)?\b|"
    r"\b(?:Warburg|Zw|W)\b",
    re.IGNORECASE,
)
_NUMBER_TOKEN = re.compile(
    r"(?<![\w.])[+-]?\d+(?:\.\d+)?"
    r"(?:\s*[·×x*]\s*10\s*\^?\s*[+\-−–]?\s*\d+)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Column:
    reported_term: str
    unit: str | None
    property: str | None
    element_role: str


@dataclass(frozen=True)
class _NativeParameterTable:
    page: int
    table_id: str
    caption: str
    header: str
    columns: tuple[_Column, ...]
    rows: tuple[tuple[str, tuple[str, ...]], ...]


def _term_key(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _column_identity(term: str) -> tuple[str | None, str]:
    key = _term_key(term)
    mapping = {
        "re": ("solution_resistance", "electrolyte"),
        "rs": ("solution_resistance", "electrolyte"),
        "rt": ("charge_transfer_resistance", "charge_transfer"),
        "rct": ("charge_transfer_resistance", "charge_transfer"),
        "rc": ("coating_resistance", "coating"),
        "rcoat": ("coating_resistance", "coating"),
        "rpore": ("pore_resistance", "pore"),
        "rcp": ("protective_layer_resistance", "protective_layer"),
        "rf": ("film_resistance", "film"),
        "rox": ("oxide_resistance", "oxide"),
        "cdl": ("cpe_parameter", "double_layer"),
        "ccp": ("cpe_parameter", "protective_layer"),
        "ccoat": ("cpe_parameter", "coating"),
        "q": ("cpe_parameter", "unknown"),
        "y0": ("cpe_parameter", "unknown"),
        "ndl": ("cpe_exponent", "double_layer"),
        "ncp": ("cpe_exponent", "protective_layer"),
        "n": ("cpe_exponent", "unknown"),
        "warburg": ("warburg_parameter", "diffusion"),
        "zw": ("warburg_parameter", "diffusion"),
        "w": ("warburg_parameter", "diffusion"),
    }
    return mapping.get(key, (None, "unknown"))


def _clean_unit(value: str) -> str | None:
    cleaned = value.strip().strip(",;:| ")
    return cleaned or None


def _parse_header(line: str) -> tuple[_Column, ...]:
    matches = list(_HEADER_TOKEN.finditer(line))
    if len(matches) < 3 or _term_key(matches[0].group()) != "time":
        return ()
    columns: list[_Column] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        term = re.sub(r"\s+", "", match.group())
        unit = _clean_unit(line[match.end():end])
        property_name, role = (None, "unknown") if index == 0 else _column_identity(term)
        columns.append(_Column(term, unit, property_name, role))
    if sum(column.property is not None for column in columns) < 2:
        return ()
    return tuple(columns)


def _parse_number(value: str) -> float | None:
    normalized = value.replace("−", "-").replace("–", "-").replace(" ", "")
    normalized = re.sub(
        r"([+-]?\d+(?:\.\d+)?)[·×x*]10\^?([+-]?\d+)",
        r"\1e\2",
        normalized,
        flags=re.IGNORECASE,
    )
    try:
        return float(normalized)
    except ValueError:
        return None


def _native_parameter_tables(source_bundle: SourceBundle) -> tuple[_NativeParameterTable, ...]:
    recovered: list[_NativeParameterTable] = []
    signatures: set[tuple[str, tuple[tuple[str, ...], ...]]] = set()
    for page in source_bundle.pages:
        text = page.text if page.origin == "ocr_extracted" else page.native_text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for caption_index, line in enumerate(lines):
            caption_match = _TABLE_CAPTION.match(line)
            if caption_match is None:
                continue
            header_index = None
            columns: tuple[_Column, ...] = ()
            for candidate_index in range(caption_index + 1, min(len(lines), caption_index + 6)):
                columns = _parse_header(lines[candidate_index])
                if columns:
                    header_index = candidate_index
                    break
            if header_index is None:
                continue

            rows: list[tuple[str, tuple[str, ...]]] = []
            for row_line in lines[header_index + 1:]:
                tokens = tuple(match.group().strip() for match in _NUMBER_TOKEN.finditer(row_line))
                if len(tokens) != len(columns):
                    if rows:
                        break
                    continue
                if _parse_number(tokens[0]) is None:
                    continue
                rows.append((row_line, tokens))
            if not rows:
                continue

            caption = " ".join(lines[caption_index:header_index])
            signature = (
                "|".join(_term_key(column.reported_term) for column in columns),
                tuple(tokens for _, tokens in rows),
            )
            if signature in signatures:
                continue
            signatures.add(signature)
            recovered.append(_NativeParameterTable(
                page=page.page,
                table_id=caption_match.group(1),
                caption=caption,
                header=lines[header_index],
                columns=columns,
                rows=tuple(rows),
            ))
    return tuple(recovered)


def _unit_token(value: str | None) -> str:
    token = (value or "").strip().casefold().replace("hours", "h").replace("hour", "h")
    return {"hr": "h", "hrs": "h"}.get(token, token)


def _matching_experiment_indices(payload: dict, exposure_raw: str, exposure_unit: str | None) -> list[int]:
    exposure_value = _parse_number(exposure_raw)
    if exposure_value is None:
        return []
    environments = {
        item.get("environment_id"): item
        for item in payload.get("environments", [])
        if isinstance(item, dict) and item.get("environment_id")
    }
    matches: list[int] = []
    for index, experiment in enumerate(payload.get("experiments", [])):
        if not isinstance(experiment, dict) or experiment.get("experiment_type") != "eis":
            continue
        environment = environments.get(experiment.get("environment_ref")) or {}
        quantity = environment.get("exposure_time")
        if not isinstance(quantity, dict) or quantity.get("value") is None:
            continue
        if float(quantity["value"]) != exposure_value:
            continue
        if _unit_token(quantity.get("unit")) != _unit_token(exposure_unit):
            continue
        matches.append(index)
    return matches


def _evidence(
    source_bundle: SourceBundle,
    table: _NativeParameterTable,
    snippet: str,
    locator: str,
) -> dict:
    return CorrosionEvidence(
        source_id=source_bundle.source.source_id,
        page=table.page,
        text_snippet=snippet,
        source_type="table",
        original_source_type="native_text",
        table_id=table.table_id,
        locator=locator,
    ).model_dump(mode="python")


def recover_corrosion_parameter_tables(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Recover fitted EIS parameters from native-text tables into existing EIS rows."""
    payload = document.model_dump(mode="python")
    tables = _native_parameter_tables(source_bundle)
    if not tables:
        return document

    environments = {
        item.get("environment_id"): item
        for item in payload.get("environments", [])
        if isinstance(item, dict) and item.get("environment_id")
    }
    for table in tables:
        time_column = table.columns[0]
        for row_index, (row_text, tokens) in enumerate(table.rows, start=1):
            experiment_indices = _matching_experiment_indices(
                payload, tokens[0], time_column.unit
            )
            if len(experiment_indices) != 1:
                continue
            experiment = payload["experiments"][experiment_indices[0]]
            row_evidence = _evidence(
                source_bundle, table, row_text,
                f"{table.table_id}:p{table.page}:r{row_index}",
            )
            experiment.setdefault("evidence", []).append(row_evidence)
            environment = environments.get(experiment.get("environment_ref"))
            if environment is not None:
                environment.setdefault("evidence", []).append(_evidence(
                    source_bundle, table, tokens[0],
                    f"{table.table_id}:p{table.page}:r{row_index}:c0",
                ))

            conditions = experiment.get("eis_conditions")
            if conditions is None:
                conditions = {}
                experiment["eis_conditions"] = conditions
            if isinstance(conditions, dict) and not conditions.get("equivalent_circuit"):
                if "model" in table.caption.casefold():
                    conditions["equivalent_circuit"] = re.sub(
                        r"^.*?with\s+the\s+", "", table.caption,
                        flags=re.IGNORECASE,
                    ).rstrip(".")
                    conditions.setdefault("evidence", []).append(_evidence(
                        source_bundle, table, table.caption,
                        f"{table.table_id}:p{table.page}:caption",
                    ))

            existing = {
                _term_key(str(metric.get("reported_term") or "")): index
                for index, metric in enumerate(experiment.get("metrics", []))
                if isinstance(metric, dict) and metric.get("reported_term")
            }
            for column_index, column in enumerate(table.columns[1:], start=1):
                if column.property is None:
                    continue
                raw_token = tokens[column_index]
                value = _parse_number(raw_token)
                if value is None:
                    continue
                raw_value = f"{raw_token} {column.unit}".strip() if column.unit else raw_token
                metric = CorrosionMetric(
                    property=column.property,
                    reported_term=column.reported_term,
                    quantity=CorrosionQuantity(
                        raw_value=raw_value,
                        value=value,
                        unit=column.unit,
                        qualifier="exact",
                    ),
                    method="equivalent-circuit fitting",
                    data_kind="fitted_parameter",
                    element_role=column.element_role,
                    equivalent_circuit_element=column.reported_term,
                    ownership="focal_work",
                    evidence=[
                        CorrosionEvidence.model_validate(_evidence(
                            source_bundle, table, raw_token,
                            f"{table.table_id}:p{table.page}:r{row_index}:c{column_index}",
                        )),
                        CorrosionEvidence.model_validate(row_evidence),
                        CorrosionEvidence.model_validate(_evidence(
                            source_bundle, table, table.header,
                            f"{table.table_id}:p{table.page}:header:c{column_index}",
                        )),
                    ],
                ).model_dump(mode="python")
                key = _term_key(column.reported_term)
                if key in existing:
                    experiment["metrics"][existing[key]] = metric
                else:
                    experiment.setdefault("metrics", []).append(metric)
                    existing[key] = len(experiment["metrics"]) - 1

    return CorrosionDocument.model_validate(payload)
