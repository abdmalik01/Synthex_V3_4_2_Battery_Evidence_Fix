"""Canonical archive → traceable analytic-row projection with typed AND filters."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from synthex_platform.core.archive import SynthexArchive
from .models import AnalyticMeasurementRow, AnalyticQuery


_SCALAR_TEXT = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d].*?)?\s*$"
)
_C_RATE_FRACTION = re.compile(r"^\s*[cC]\s*/\s*(\d+(?:\.\d+)?)\s*$")


def _evidence_refs(evidence) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    items = [item.model_dump(exclude_none=True) for item in evidence]
    visual = [item for item in items if item.get("table_id") or item.get("figure_id")]
    origins = [str(item.get("source_type", "unknown")) for item in items]
    return items, visual, list(dict.fromkeys(origins))


def _numeric(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _scalar_condition(value: Any) -> tuple[Any, str | None, str | None]:
    """Return a plotting value plus optional raw/unit text without scientific conversion.

    Only a single explicit scalar is parsed. Ranges, voltage windows, prose, and compound
    expressions remain categorical strings. C/10-style rates are a notation exception:
    they are represented as the dimensionless C-rate scalar 0.1 while the source string
    remains available in ``*_raw``.
    """
    numeric = _numeric(value)
    if numeric is not None:
        return numeric, None, None
    if not isinstance(value, str):
        return value, None, None
    text = value.strip()
    if not text:
        return text, None, None
    fraction = _C_RATE_FRACTION.fullmatch(text)
    if fraction:
        denominator = float(fraction.group(1))
        if denominator:
            return 1.0 / denominator, text, "C"
    match = _SCALAR_TEXT.fullmatch(text)
    if not match:
        return text, None, None
    try:
        parsed = float(match.group(1))
    except ValueError:
        return text, None, None
    suffix = (match.group(2) or "").strip() or None
    # Reject scalar-looking text whose suffix contains another number. This prevents
    # accidental parsing of ranges/compound conditions such as "2-4 V" or "1/2 C".
    if suffix and re.search(r"\d", suffix):
        return text, None, None
    return parsed, text, suffix


def _condition_mapping(values: Mapping[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, source in (values or {}).items():
        raw_value = None
        unit = None
        candidate = source
        if isinstance(source, Mapping):
            candidate = source.get("normalized_value")
            if _numeric(candidate) is None:
                candidate = source.get("value")
            if candidate is None:
                candidate = source.get("raw_value")
            raw_value = source.get("raw_value")
            unit = source.get("normalized_unit") or source.get("unit")
        parsed, parsed_raw, parsed_unit = _scalar_condition(candidate)
        result[key] = parsed
        raw = raw_value if raw_value not in (None, "") else parsed_raw
        if raw not in (None, "") and raw != parsed:
            result[f"{key}_raw"] = raw
        chosen_unit = unit or parsed_unit
        if chosen_unit:
            result[f"{key}_unit"] = chosen_unit
    return result


def _conditions(measurements) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for measurement in measurements:
        candidate = measurement.normalized_value if _numeric(measurement.normalized_value) is not None else measurement.value
        if candidate is None:
            candidate = measurement.raw_value
        parsed, parsed_raw, parsed_unit = _scalar_condition(candidate)
        if parsed is None:
            continue
        result[measurement.property] = parsed
        raw = measurement.raw_value if measurement.raw_value not in (None, "") else parsed_raw
        if raw not in (None, "") and raw != parsed:
            result[f"{measurement.property}_raw"] = raw
        unit = measurement.normalized_unit or measurement.unit or parsed_unit
        if unit:
            result[f"{measurement.property}_unit"] = unit
    return result


def _matches(row: AnalyticMeasurementRow, query: AnalyticQuery) -> bool:
    if query.property_name and row.property_name != query.property_name:
        return False
    if query.material_id and row.material_id != query.material_id:
        return False
    if query.material_contains and query.material_contains.lower() not in (row.material_label or "").lower():
        return False
    if query.method_contains and query.method_contains.lower() not in (row.method or "").lower():
        return False
    if query.source_id and row.source_id != query.source_id:
        return False
    if query.experiment_type and not (row.modality == "experimental" and row.record_type == query.experiment_type):
        return False
    if query.calculation_type and not (row.modality == "computational" and row.record_type == query.calculation_type):
        return False
    if query.modalities and row.modality not in query.modalities:
        return False
    if query.provenance_origin and query.provenance_origin not in row.provenance_origins:
        return False
    for value, lower, upper in (
        (row.value, query.value_min, query.value_max),
        (row.conditions.get("temperature"), query.temperature_min, query.temperature_max),
        (row.conditions.get("cycle"), query.cycle_min, query.cycle_max),
    ):
        numeric = _numeric(value)
        if lower is not None and (numeric is None or numeric < lower):
            return False
        if upper is not None and (numeric is None or numeric > upper):
            return False
    return True


def project_archives(archives: Iterable[SynthexArchive], query: AnalyticQuery | None = None) -> list[AnalyticMeasurementRow]:
    """Project only canonical archive measurements; raw domain payloads are never read.

    Parent experiment/calculation conditions and value-specific measurement conditions are
    merged for analytics. The latter take precedence because they are the narrowest
    source-linked context for a reported value (for example cycle, C-rate, or temperature).
    """
    query = query or AnalyticQuery()
    rows: list[AnalyticMeasurementRow] = []
    for archive in archives:
        source_id = archive.sources[0].source_id if archive.sources else None
        materials = {item.material_id: item for item in archive.materials}
        for experiment in archive.experiments:
            parent_conditions = _conditions(experiment.conditions)
            for measurement in experiment.outputs:
                evidence, visual, origins = _evidence_refs(measurement.evidence or experiment.evidence)
                row_conditions = {**parent_conditions, **_condition_mapping(measurement.conditions)}
                for material_id in experiment.material_ids or [None]:
                    material = materials.get(material_id) if material_id else None
                    value = measurement.normalized_value if _numeric(measurement.normalized_value) is not None else measurement.value
                    rows.append(AnalyticMeasurementRow(
                        archive_id=archive.metadata.archive_id,
                        source_id=source_id,
                        material_id=material_id,
                        device_id=experiment.device_id,
                        experiment_id=experiment.experiment_id,
                        modality="experimental",
                        property_name=measurement.property,
                        raw_property_name=measurement.property,
                        value=_numeric(value),
                        raw_value=measurement.raw_value,
                        unit=measurement.unit,
                        normalized_unit=measurement.normalized_unit,
                        qualifier=measurement.qualifier,
                        material_label=(material.name or material.formula) if material else None,
                        method=measurement.method or experiment.protocol,
                        record_type=experiment.experiment_type,
                        conditions=row_conditions,
                        evidence_references=evidence,
                        visual_evidence_references=visual,
                        provenance_origins=origins,
                    ))
        for calculation in archive.calculations:
            parent_conditions = _conditions(calculation.parameters)
            for measurement in calculation.outputs:
                evidence, visual, origins = _evidence_refs(measurement.evidence or calculation.evidence)
                row_conditions = {**parent_conditions, **_condition_mapping(measurement.conditions)}
                for material_id in calculation.material_ids or [None]:
                    material = materials.get(material_id) if material_id else None
                    value = measurement.normalized_value if _numeric(measurement.normalized_value) is not None else measurement.value
                    rows.append(AnalyticMeasurementRow(
                        archive_id=archive.metadata.archive_id,
                        source_id=source_id,
                        material_id=material_id,
                        calculation_id=calculation.calculation_id,
                        modality="computational",
                        property_name=measurement.property,
                        raw_property_name=measurement.property,
                        value=_numeric(value),
                        raw_value=measurement.raw_value,
                        unit=measurement.unit,
                        normalized_unit=measurement.normalized_unit,
                        qualifier=measurement.qualifier,
                        material_label=(material.name or material.formula) if material else None,
                        method=measurement.method or calculation.method,
                        record_type=calculation.calculation_type,
                        conditions=row_conditions,
                        evidence_references=evidence,
                        visual_evidence_references=visual,
                        provenance_origins=origins,
                    ))
    return [row for row in rows if _matches(row, query)]