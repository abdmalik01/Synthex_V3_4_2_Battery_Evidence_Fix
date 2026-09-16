"""Provenance-safe analytics enrichment for researcher-facing result rows.

The canonical archive remains unchanged.  This module only adds process parameters
that can be joined unambiguously through material -> processed_by -> process lineage.
Conflicting process values are retained as diagnostics rather than flattened.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Mapping

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.core.models import Measurement, ProcessStep

from .csv_exporter import project_results_rows as _project_results_rows


def _measurement_payload(measurement: Measurement, process: ProcessStep) -> dict[str, Any]:
    evidence = [item.model_dump(mode="json", exclude_none=True) for item in measurement.evidence]
    return {
        key: value
        for key, value in {
            "raw_value": measurement.raw_value,
            "value": measurement.value,
            "unit": measurement.unit,
            "normalized_value": measurement.normalized_value,
            "normalized_unit": measurement.normalized_unit,
            "qualifier": measurement.qualifier,
            "process_id": process.process_id,
            "process_name": process.name,
            "process_family": process.family,
            "evidence": evidence,
        }.items()
        if value not in (None, "", [])
    }


def _rendered_value(payload: Mapping[str, Any]) -> str:
    raw = payload.get("raw_value")
    if raw not in (None, ""):
        return str(raw)
    value = payload.get("normalized_value")
    unit = payload.get("normalized_unit")
    if value not in (None, ""):
        return f"{value} {unit or ''}".strip()
    value = payload.get("value")
    unit = payload.get("unit")
    return f"{value} {unit or ''}".strip() if value not in (None, "") else ""


def _material_process_index(archive: SynthexArchive) -> dict[str, list[ProcessStep]]:
    process_index = {item.process_id: item for item in archive.processes}
    linked: dict[str, list[ProcessStep]] = defaultdict(list)

    for relation in archive.relationships:
        if relation.predicate != "processed_by":
            continue
        process = process_index.get(relation.object_id)
        if process is not None:
            linked[relation.subject_id].append(process)

    # Compatibility fallback for archives that contain process outputs but no
    # explicit processed_by relationship.
    material_ids = {item.material_id for item in archive.materials}
    for process in archive.processes:
        for output_id in process.outputs:
            if output_id in material_ids and process not in linked[output_id]:
                linked[output_id].append(process)

    return {
        material_id: sorted(processes, key=lambda item: (item.sequence_index or 0, item.process_id))
        for material_id, processes in linked.items()
    }


def _lineage_context(archive: SynthexArchive, material_ids: list[str]) -> dict[str, Any]:
    process_index = _material_process_index(archive)
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for material_id in material_ids:
        for process in process_index.get(material_id, []):
            for measurement in process.parameters:
                # Canonical process parameters have already passed the relevant
                # domain admission gate. Require source evidence here as a second
                # projection-level guard rather than inventing context from text.
                if not measurement.evidence:
                    continue
                payload = _measurement_payload(measurement, process)
                if _rendered_value(payload):
                    candidates[measurement.property].append(payload)

    context: dict[str, Any] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    for property_name, values in sorted(candidates.items()):
        unique: dict[str, dict[str, Any]] = {}
        for payload in values:
            unique.setdefault(_rendered_value(payload), payload)
        if len(unique) == 1:
            # Material-linked processed_by records are synthesis/material-processing
            # lineage in the current archive architecture. Namespace them so they
            # cannot overwrite experimental temperature, duration, etc.
            context[f"synthesis_{property_name}"] = next(iter(unique.values()))
        elif len(unique) > 1:
            conflicts[property_name] = list(unique.values())

    if conflicts:
        context["process_lineage_conflicts"] = conflicts
    return context


def _parse_conditions(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("conditions_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def project_results_rows(
    archive: SynthexArchive, *, include_quarantined: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Project result rows and add unambiguous material-process lineage context."""
    rows = _project_results_rows(archive, include_quarantined=include_quarantined)
    enriched: list[dict[str, Any]] = []

    for source_row in rows:
        row = dict(source_row)
        if (
            row.get("record_type") == "experiment"
            and row.get("measurement_role") == "result"
            and row.get("admission_status") != "quarantined"
        ):
            material_ids = [item for item in str(row.get("material_ids") or "").split("|") if item]
            lineage = _lineage_context(archive, material_ids)
            if lineage:
                conditions = _parse_conditions(row)
                # Direct experimental/result conditions always win.  Lineage is
                # namespaced, so this should normally be collision-free anyway.
                for key, value in lineage.items():
                    conditions.setdefault(key, value)
                row["conditions_json"] = json.dumps(
                    conditions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
        enriched.append(row)

    return tuple(enriched)
