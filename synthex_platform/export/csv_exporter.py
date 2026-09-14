"""Researcher-facing CSV projections for :class:`SynthexArchive`.

JSON remains the canonical representation. These functions only read a validated
archive and create deterministic tabular views; they never mutate or reconstruct it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import json
import re
from typing import Any, Iterable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.models import Evidence, Measurement, SourceRecord


UTF8_BOM = "\ufeff"

RESULTS_HEADERS = (
    "record_id", "record_type", "measurement_role", "source_id", "source_title", "doi",
    "source_page", "domain", "ownership", "admission_status", "quarantine_reason",
    "quarantine_path", "material_ids", "material_names", "material_formulas", "material_states",
    "process_id", "process_name", "experiment_id", "experiment_type", "calculation_id",
    "calculation_type", "reaction", "metric", "product", "value", "raw_value", "qualifier",
    "unit", "normalized_value", "normalized_unit", "uncertainty", "uncertainty_unit",
    "temperature", "pressure", "potential", "reference_electrode", "electrolyte", "pH",
    "normalization_basis", "duration", "time_on_stream", "method", "conditions_json",
    "evidence_origin", "evidence_page", "evidence_snippet", "evidence_strength", "estimated",
    "quarantined_object_json",
)

TABLE_HEADERS = {
    "sources.csv": (
        "source_id", "source_type", "title", "doi", "url", "year", "authors", "license", "checksum",
    ),
    "materials.csv": (
        "material_id", "name", "formula", "phase", "state", "composition_json", "elements",
        "structure_json", "morphology_json", "tags", "source_id", "evidence_ids",
    ),
    "processes.csv": (
        "process_id", "name", "family", "sequence_index", "inputs", "outputs", "atmosphere",
        "equipment", "source_id", "evidence_ids",
    ),
    "experiments.csv": (
        "experiment_id", "experiment_type", "material_ids", "device_ids", "target", "protocol",
        "source_id", "evidence_ids",
    ),
    "calculations.csv": (
        "calculation_id", "calculation_type", "material_ids", "code", "method", "functional",
        "model_json", "source_id", "evidence_ids",
    ),
    "measurements.csv": RESULTS_HEADERS,
    "relationships.csv": (
        "relation_id", "subject_id", "predicate", "object_id", "attributes_json", "source_id", "evidence_ids",
    ),
    "evidence.csv": (
        "evidence_id", "linked_record_id", "linked_record_type", "source_id", "page", "section",
        "source_type", "original_source_type", "verbatim_match", "text_snippet", "table_id",
        "figure_id", "locator", "confidence", "evidence_origin", "evidence_strength", "estimated",
    ),
}

_TEXT_RISK = re.compile(r"^[=+\-@]")
_NEGATIVE_NUMBER = re.compile(r"^-\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?(?:\s*[A-Za-z%°Ωµμ/^-].*)?$")


@dataclass(frozen=True)
class CsvExportBundle:
    """Immutable mapping of stable CSV filenames to UTF-8 encoded payloads."""

    files: Mapping[str, bytes]


def _json(value: Any) -> str:
    if value in (None, {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_cell(value: Any) -> Any:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if _TEXT_RISK.match(value) and not _NEGATIVE_NUMBER.match(value.strip()):
        return "'" + value
    return value


def _csv_bytes(headers: Iterable[str], rows: Iterable[Mapping[str, Any]], *, bom: bool) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers), extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _text_cell(row.get(key)) for key in writer.fieldnames})
    text = buffer.getvalue()
    return ((UTF8_BOM if bom else "") + text).encode("utf-8")


def _stable_export_id(prefix: str, *parts: Any) -> str:
    canonical = "\x1f".join(_json(part) if isinstance(part, (dict, list)) else str(part or "") for part in parts)
    return f"{prefix}-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def _source_index(archive: SynthexArchive) -> tuple[dict[str, SourceRecord], SourceRecord | None]:
    index = {item.source_id: item for item in archive.sources}
    return index, archive.sources[0] if archive.sources else None


def _source_for_evidence(
    evidence: list[Evidence], source_index: Mapping[str, SourceRecord], primary: SourceRecord | None,
) -> SourceRecord | None:
    if evidence and evidence[0].source_id in source_index:
        return source_index[evidence[0].source_id]
    return primary


def _evidence_origin(item: Evidence | Mapping[str, Any] | None) -> str:
    if item is None:
        return ""
    get = item.get if isinstance(item, Mapping) else lambda key, default=None: getattr(item, key, default)
    return str(get("original_source_type") or get("source_type") or "")


def _evidence_semantics(item: Evidence | Mapping[str, Any] | None) -> tuple[str, bool]:
    if item is None:
        return "unverified", False
    get = item.get if isinstance(item, Mapping) else lambda key, default=None: getattr(item, key, default)
    explicit = get("evidence_strength")
    explicit_estimated = get("estimated")
    origin = _evidence_origin(item)
    estimated = bool(explicit_estimated) or origin == "figure_digitized"
    if explicit:
        return str(explicit), estimated
    if origin == "ocr_extracted" and get("verbatim_match") is True:
        return "verified_ocr", estimated
    if origin == "figure_digitized":
        return "estimated_digitized", True
    if get("verbatim_match") is True:
        return "verified_native", estimated
    return "unverified", estimated


def _evidence_summary(evidence: list[Evidence] | list[Mapping[str, Any]]) -> dict[str, Any]:
    item = evidence[0] if evidence else None
    strength, estimated = _evidence_semantics(item)
    get = item.get if isinstance(item, Mapping) else lambda key, default=None: getattr(item, key, default)
    return {
        "evidence_origin": _evidence_origin(item),
        "evidence_page": get("page") if item is not None else "",
        "evidence_snippet": get("text_snippet") if item is not None else "",
        "evidence_strength": strength,
        "estimated": estimated,
    }


def _material_context(archive: SynthexArchive, material_ids: list[str]) -> dict[str, str]:
    index = {item.material_id: item for item in archive.materials}
    materials = [index[item_id] for item_id in material_ids if item_id in index]
    states = []
    for item in materials:
        state = item.structure.get("catalyst_state") or item.phase
        states.append(str(state or ""))
    return {
        "material_ids": "|".join(item.material_id for item in materials),
        "material_names": "|".join(item.name or "" for item in materials),
        "material_formulas": "|".join(item.formula or "" for item in materials),
        "material_states": "|".join(states),
    }


def _render_quantity(value: Any) -> Any:
    if isinstance(value, Mapping):
        raw = value.get("raw_value")
        if raw not in (None, ""):
            return raw
        scalar = value.get("value")
        unit = value.get("unit")
        if scalar not in (None, ""):
            return f"{scalar} {unit}".strip()
        return _json(value)
    return "" if value is None else value


def _condition(conditions: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if conditions.get(key) not in (None, "", [], {}):
            return _render_quantity(conditions[key])
    return ""


def _measurement_value(measurement: Measurement) -> Any:
    if measurement.raw_value not in (None, ""):
        return measurement.raw_value
    if measurement.value not in (None, ""):
        return f"{measurement.value} {measurement.unit or ''}".strip()
    return ""


def _measurement_context(measurements: Iterable[Measurement]) -> dict[str, Any]:
    return {
        item.property: _measurement_value(item)
        for item in measurements
        if _measurement_value(item) not in (None, "")
    }


def _measurement_row(
    archive: SynthexArchive,
    measurement: Measurement,
    *,
    parent_id: str,
    record_type: str,
    measurement_role: str,
    ordinal: int,
    material_ids: list[str],
    process_id: str = "",
    process_name: str = "",
    experiment_id: str = "",
    experiment_type: str = "",
    calculation_id: str = "",
    calculation_type: str = "",
    reaction: str = "",
    parent_conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_index, primary = _source_index(archive)
    source = _source_for_evidence(measurement.evidence, source_index, primary)
    conditions = {**(parent_conditions or {}), **measurement.conditions}
    evidence = _evidence_summary(measurement.evidence)
    own_value = _measurement_value(measurement)
    return {
        "record_id": _stable_export_id("meas", parent_id, measurement_role, ordinal, measurement.model_dump(mode="json")),
        "record_type": record_type,
        "measurement_role": measurement_role,
        "source_id": source.source_id if source else "",
        "source_title": source.title if source else "",
        "doi": source.doi if source else "",
        "source_page": evidence["evidence_page"],
        "domain": archive.metadata.domain or "",
        "ownership": "focal_work",
        "admission_status": "canonical",
        **_material_context(archive, material_ids),
        "process_id": process_id,
        "process_name": process_name,
        "experiment_id": experiment_id,
        "experiment_type": experiment_type,
        "calculation_id": calculation_id,
        "calculation_type": calculation_type,
        "reaction": reaction or _condition(conditions, "reaction", "reaction_class"),
        "metric": measurement.property,
        "product": _condition(conditions, "product"),
        "value": measurement.value,
        "raw_value": measurement.raw_value,
        "qualifier": measurement.qualifier,
        "unit": measurement.unit,
        "normalized_value": measurement.normalized_value,
        "normalized_unit": measurement.normalized_unit,
        "uncertainty": measurement.uncertainty,
        "uncertainty_unit": measurement.uncertainty_unit,
        "temperature": _condition(conditions, "temperature") or (own_value if measurement.property == "temperature" else ""),
        "pressure": _condition(conditions, "pressure") or (own_value if measurement.property == "pressure" else ""),
        "potential": _condition(conditions, "reported_potential_raw", "potential") or (own_value if measurement.property == "potential" else ""),
        "reference_electrode": _condition(conditions, "reported_reference", "reference_electrode"),
        "electrolyte": _condition(conditions, "electrolyte"),
        "pH": _condition(conditions, "pH", "ph"),
        "normalization_basis": _condition(conditions, "normalization_basis", "normalization_key"),
        "duration": _condition(conditions, "duration") or (own_value if measurement.property == "duration" else ""),
        "time_on_stream": _condition(conditions, "time_on_stream") or (own_value if measurement.property == "time_on_stream" else ""),
        "method": measurement.method,
        "conditions_json": _json(conditions),
        **evidence,
    }


def _canonical_measurement_rows(archive: SynthexArchive) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for process in sorted(archive.processes, key=lambda item: item.process_id):
        material_ids = [item for item in process.outputs if any(m.material_id == item for m in archive.materials)]
        process_context = _measurement_context(process.parameters)
        for index, measurement in enumerate(process.parameters):
            rows.append(_measurement_row(
                archive, measurement, parent_id=process.process_id, record_type="process",
                measurement_role="parameter", ordinal=index, material_ids=material_ids,
                process_id=process.process_id, process_name=process.name,
                parent_conditions=process_context,
            ))
    for experiment in sorted(archive.experiments, key=lambda item: item.experiment_id):
        experiment_context = _measurement_context(experiment.conditions)
        for role, measurements in (("condition", experiment.conditions), ("result", experiment.outputs)):
            for index, measurement in enumerate(measurements):
                rows.append(_measurement_row(
                    archive, measurement, parent_id=experiment.experiment_id, record_type="experiment",
                    measurement_role=role, ordinal=index, material_ids=experiment.material_ids,
                    experiment_id=experiment.experiment_id, experiment_type=experiment.experiment_type,
                    reaction=experiment.target or "",
                    parent_conditions=experiment_context,
                ))
    for calculation in sorted(archive.calculations, key=lambda item: item.calculation_id):
        calculation_context = _measurement_context(calculation.parameters)
        for role, measurements in (("parameter", calculation.parameters), ("result", calculation.outputs)):
            for index, measurement in enumerate(measurements):
                rows.append(_measurement_row(
                    archive, measurement, parent_id=calculation.calculation_id, record_type="calculation",
                    measurement_role=role, ordinal=index, material_ids=calculation.material_ids,
                    calculation_id=calculation.calculation_id, calculation_type=calculation.calculation_type,
                    parent_conditions=calculation_context,
                ))
    return sorted(rows, key=lambda row: (str(row["record_type"]), str(row["record_id"])))


def _quarantine_entries(archive: SynthexArchive) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for payload_index, payload in enumerate(archive.domain_payloads):
        values = payload.values
        candidates: list[Any] = []
        audit = values.get("admissibility_audit")
        if isinstance(audit, Mapping):
            candidates.extend(audit.get("quarantine") or [])
        admissibility = values.get("admissibility")
        if isinstance(admissibility, Mapping):
            candidates.extend(admissibility.get("quarantine") or [])
            candidates.extend(admissibility.get("quarantined_objects") or [])
        # Some older payloads expose only the battery audit at the top level.
        if isinstance(values.get("quarantine"), list):
            candidates.extend(values["quarantine"])
        seen: set[str] = set()
        for index, item in enumerate(candidates):
            if not isinstance(item, Mapping):
                continue
            signature = _json(item)
            if signature in seen:
                continue
            seen.add(signature)
            entries.append({"domain": payload.domain, "payload_index": payload_index, "index": index, **dict(item)})
    return entries


def _quarantine_rows(archive: SynthexArchive) -> list[dict[str, Any]]:
    source_index, primary = _source_index(archive)
    rows = []
    for entry in _quarantine_entries(archive):
        obj = entry.get("object") or entry.get("raw_object") or entry
        obj = obj if isinstance(obj, Mapping) else {"value": obj}
        evidence_items = obj.get("evidence") if isinstance(obj.get("evidence"), list) else entry.get("evidence")
        evidence_items = [item for item in (evidence_items or []) if isinstance(item, Mapping)]
        evidence = _evidence_summary(evidence_items)
        source_id_value = evidence_items[0].get("source_id") if evidence_items else None
        source = source_index.get(str(source_id_value)) or primary
        conditions = obj.get("conditions") if isinstance(obj.get("conditions"), Mapping) else {}
        path = str(entry.get("path") or entry.get("local_id") or "")
        rows.append({
            "record_id": _stable_export_id("q", archive.metadata.archive_id, entry["payload_index"], path, entry["index"], obj),
            "record_type": str(entry.get("kind") or "quarantined_object"),
            "measurement_role": "quarantined",
            "source_id": source.source_id if source else "",
            "source_title": source.title if source else "",
            "doi": source.doi if source else "",
            "source_page": evidence["evidence_page"],
            "domain": entry.get("domain") or archive.metadata.domain or "",
            "ownership": entry.get("ownership") or obj.get("ownership") or "unknown",
            "admission_status": "quarantined",
            "quarantine_reason": entry.get("reason") or "unspecified",
            "quarantine_path": path,
            "metric": obj.get("property") or obj.get("metric") or "",
            "product": obj.get("product") or _condition(conditions, "product"),
            "value": obj.get("value"),
            "raw_value": obj.get("raw_value"),
            "qualifier": obj.get("qualifier") or "",
            "unit": obj.get("unit") or "",
            "normalized_value": obj.get("normalized_value"),
            "normalized_unit": obj.get("normalized_unit") or "",
            "temperature": _condition(conditions, "temperature"),
            "pressure": _condition(conditions, "pressure"),
            "potential": _condition(conditions, "reported_potential_raw", "potential"),
            "reference_electrode": _condition(conditions, "reported_reference", "reference_electrode"),
            "electrolyte": _condition(conditions, "electrolyte"),
            "pH": _condition(conditions, "pH", "ph"),
            "normalization_basis": _condition(conditions, "normalization_basis", "normalization_key"),
            "duration": _condition(conditions, "duration"),
            "time_on_stream": _condition(conditions, "time_on_stream"),
            "method": obj.get("method") or "",
            "conditions_json": _json(conditions),
            **evidence,
            "quarantined_object_json": _json(obj),
        })
    return sorted(rows, key=lambda row: str(row["record_id"]))


def _all_results_rows(archive: SynthexArchive, include_quarantined: bool) -> list[dict[str, Any]]:
    rows = _canonical_measurement_rows(archive)
    if include_quarantined:
        rows.extend(_quarantine_rows(archive))
    return sorted(rows, key=lambda row: (str(row.get("admission_status")), str(row["record_id"])))


def _evidence_rows(archive: SynthexArchive, measurement_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    rows: list[dict[str, Any]] = []
    links: dict[str, list[str]] = {}

    def add(linked_id: str, linked_type: str, items: Iterable[Evidence]) -> None:
        for index, item in enumerate(items):
            payload = item.model_dump(mode="json", exclude_none=True)
            evidence_id = _stable_export_id("ev", linked_id, index, payload)
            strength, estimated = _evidence_semantics(item)
            rows.append({
                "evidence_id": evidence_id, "linked_record_id": linked_id, "linked_record_type": linked_type,
                **payload, "evidence_origin": _evidence_origin(item), "evidence_strength": strength,
                "estimated": estimated,
            })
            links.setdefault(linked_id, []).append(evidence_id)

    for item in archive.materials:
        add(item.material_id, "material", item.evidence)
    for item in archive.processes:
        add(item.process_id, "process", item.evidence)
        for index, measurement in enumerate(item.parameters):
            row_id = _stable_export_id("meas", item.process_id, "parameter", index, measurement.model_dump(mode="json"))
            add(row_id, "measurement", measurement.evidence)
    for item in archive.experiments:
        add(item.experiment_id, "experiment", item.evidence)
        for role, measurements in (("condition", item.conditions), ("result", item.outputs)):
            for index, measurement in enumerate(measurements):
                row_id = _stable_export_id("meas", item.experiment_id, role, index, measurement.model_dump(mode="json"))
                add(row_id, "measurement", measurement.evidence)
    for item in archive.calculations:
        add(item.calculation_id, "calculation", item.evidence)
        for role, measurements in (("parameter", item.parameters), ("result", item.outputs)):
            for index, measurement in enumerate(measurements):
                row_id = _stable_export_id("meas", item.calculation_id, role, index, measurement.model_dump(mode="json"))
                add(row_id, "measurement", measurement.evidence)
    for item in archive.relationships:
        add(item.relation_id, "relationship", item.evidence)
    for measurement_row in measurement_rows:
        if measurement_row.get("admission_status") != "quarantined":
            continue
        raw_object = measurement_row.get("quarantined_object_json")
        if not raw_object:
            continue
        obj = json.loads(str(raw_object))
        evidence = obj.get("evidence") if isinstance(obj, Mapping) else None
        for index, item in enumerate(evidence or []):
            if not isinstance(item, Mapping):
                continue
            evidence_id = _stable_export_id("ev", measurement_row["record_id"], index, item)
            strength, estimated = _evidence_semantics(item)
            rows.append({
                "evidence_id": evidence_id,
                "linked_record_id": measurement_row["record_id"],
                "linked_record_type": "quarantined_measurement",
                **dict(item),
                "evidence_origin": _evidence_origin(item),
                "evidence_strength": strength,
                "estimated": estimated,
            })
            links.setdefault(str(measurement_row["record_id"]), []).append(evidence_id)
    return sorted(rows, key=lambda row: row["evidence_id"]), links


def export_results_csv(
    archive: SynthexArchive, *, include_quarantined: bool = False, excel_compatible: bool = True,
) -> bytes:
    """Return a one-observation-per-row CSV derived from ``archive``."""
    return export_results_rows_csv(
        project_results_rows(archive, include_quarantined=include_quarantined),
        excel_compatible=excel_compatible,
    )


def project_results_rows(
    archive: SynthexArchive, *, include_quarantined: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Project archive measurements into immutable, deterministic result rows."""
    if not isinstance(archive, SynthexArchive):
        raise TypeError("archive must be a validated SynthexArchive")
    return tuple(_all_results_rows(archive, include_quarantined))


def export_results_rows_csv(
    rows: Iterable[Mapping[str, Any]], *, excel_compatible: bool = True,
) -> bytes:
    """Encode a filtered result projection without touching the source archive."""
    stable_rows = sorted((dict(row) for row in rows), key=lambda row: str(row.get("record_id", "")))
    return _csv_bytes(RESULTS_HEADERS, stable_rows, bom=excel_compatible)


def export_csv_bundle(
    archive: SynthexArchive, *, include_quarantined: bool = False, excel_compatible: bool = True,
) -> CsvExportBundle:
    """Return a relational CSV bundle with stable headers and IDs."""
    if not isinstance(archive, SynthexArchive):
        raise TypeError("archive must be a validated SynthexArchive")
    source_index, primary = _source_index(archive)
    measurements = _all_results_rows(archive, include_quarantined)
    evidence_rows, evidence_links = _evidence_rows(archive, measurements)
    source_id_value = primary.source_id if primary else ""

    rows: dict[str, list[dict[str, Any]]] = {
        "sources.csv": [{
            **item.model_dump(mode="json", exclude_none=True), "authors": "|".join(item.authors),
        } for item in sorted(archive.sources, key=lambda value: value.source_id)],
        "materials.csv": [{
            "material_id": item.material_id, "name": item.name, "formula": item.formula, "phase": item.phase,
            "state": item.structure.get("catalyst_state") or "", "composition_json": _json(item.composition),
            "elements": "|".join(item.elements), "structure_json": _json(item.structure),
            "morphology_json": _json(item.morphology), "tags": "|".join(item.tags),
            "source_id": (item.evidence[0].source_id if item.evidence else source_id_value) or "",
            "evidence_ids": "|".join(evidence_links.get(item.material_id, [])),
        } for item in sorted(archive.materials, key=lambda value: value.material_id)],
        "processes.csv": [{
            "process_id": item.process_id, "name": item.name, "family": item.family,
            "sequence_index": item.sequence_index, "inputs": "|".join(item.inputs), "outputs": "|".join(item.outputs),
            "atmosphere": item.atmosphere, "equipment": item.equipment,
            "source_id": (item.evidence[0].source_id if item.evidence else source_id_value) or "",
            "evidence_ids": "|".join(evidence_links.get(item.process_id, [])),
        } for item in sorted(archive.processes, key=lambda value: value.process_id)],
        "experiments.csv": [{
            "experiment_id": item.experiment_id, "experiment_type": item.experiment_type,
            "material_ids": "|".join(item.material_ids),
            "device_ids": "|".join(sorted(set(item.device_ids + ([item.device_id] if item.device_id else [])))),
            "target": item.target, "protocol": item.protocol,
            "source_id": (item.evidence[0].source_id if item.evidence else source_id_value) or "",
            "evidence_ids": "|".join(evidence_links.get(item.experiment_id, [])),
        } for item in sorted(archive.experiments, key=lambda value: value.experiment_id)],
        "calculations.csv": [{
            "calculation_id": item.calculation_id, "calculation_type": item.calculation_type,
            "material_ids": "|".join(item.material_ids), "code": item.code, "method": item.method,
            "functional": item.functional, "model_json": _json(item.model),
            "source_id": (item.evidence[0].source_id if item.evidence else source_id_value) or "",
            "evidence_ids": "|".join(evidence_links.get(item.calculation_id, [])),
        } for item in sorted(archive.calculations, key=lambda value: value.calculation_id)],
        "measurements.csv": measurements,
        "relationships.csv": [{
            "relation_id": item.relation_id, "subject_id": item.subject_id, "predicate": item.predicate,
            "object_id": item.object_id, "attributes_json": _json(item.attributes),
            "source_id": (item.evidence[0].source_id if item.evidence else source_id_value) or "",
            "evidence_ids": "|".join(evidence_links.get(item.relation_id, [])),
        } for item in sorted(archive.relationships, key=lambda value: value.relation_id)],
        "evidence.csv": evidence_rows,
    }
    files = {
        name: _csv_bytes(TABLE_HEADERS[name], rows[name], bom=excel_compatible)
        for name in TABLE_HEADERS
    }
    return CsvExportBundle(files=files)


def export_csv_bundle_zip(
    archive: SynthexArchive, *, include_quarantined: bool = False, excel_compatible: bool = True,
) -> bytes:
    """Return the relational bundle as a deterministic ZIP payload."""
    bundle = export_csv_bundle(
        archive, include_quarantined=include_quarantined, excel_compatible=excel_compatible,
    )
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive_zip:
        for name in sorted(bundle.files):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive_zip.writestr(info, bundle.files[name])
    return output.getvalue()
