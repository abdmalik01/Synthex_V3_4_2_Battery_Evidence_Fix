"""Deterministic, read-only projections used by Archive Explorer V1."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Any, Iterable, Mapping

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.export import export_csv_bundle, project_results_rows


FILTER_FIELDS = (
    "domain",
    "source_title",
    "material_names",
    "experiment_type",
    "reaction",
    "metric",
    "product",
    "admission_status",
    "ownership",
    "evidence_origin",
)


@dataclass(frozen=True)
class ExplorerFilters:
    domain: tuple[str, ...] = ()
    source_title: tuple[str, ...] = ()
    material_names: tuple[str, ...] = ()
    experiment_type: tuple[str, ...] = ()
    reaction: tuple[str, ...] = ()
    metric: tuple[str, ...] = ()
    product: tuple[str, ...] = ()
    admission_status: tuple[str, ...] = ()
    ownership: tuple[str, ...] = ()
    evidence_origin: tuple[str, ...] = ()
    estimated: bool | None = None
    search: str = ""


@dataclass(frozen=True)
class ArchiveExplorerData:
    results: tuple[dict[str, Any], ...]
    materials: tuple[dict[str, Any], ...]
    processes: tuple[dict[str, Any], ...]
    experiments: tuple[dict[str, Any], ...]
    calculations: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]


def _decode_csv(payload: bytes) -> tuple[dict[str, Any], ...]:
    return tuple(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))


def _calculation_rows(archive: SynthexArchive) -> tuple[dict[str, Any], ...]:
    material_index = {item.material_id: item for item in archive.materials}
    source = archive.sources[0] if archive.sources else None
    rows: list[dict[str, Any]] = []
    for calculation in sorted(archive.calculations, key=lambda item: item.calculation_id):
        materials = [material_index[item] for item in calculation.material_ids if item in material_index]
        outputs = calculation.outputs or [None]
        for output in outputs:
            evidence = (output.evidence if output is not None else calculation.evidence)
            item = evidence[0] if evidence else None
            origin = (item.original_source_type or item.source_type.value) if item else ""
            strength = (
                "verified_ocr" if item and item.verbatim_match is True and origin == "ocr_extracted"
                else "estimated_digitized" if origin == "figure_digitized"
                else "verified_native" if item and item.verbatim_match is True
                else "unverified"
            )
            rows.append({
                "calculation_id": calculation.calculation_id,
                "calculation_type": calculation.calculation_type,
                "material": " | ".join(value.name or value.formula or value.material_id for value in materials),
                "calculated_property": output.property if output else "",
                "value": output.value if output else "",
                "raw_value": output.raw_value if output else "",
                "unit": output.unit if output else "",
                "method": output.method if output and output.method else calculation.method or "",
                "functional": calculation.functional or "",
                "software": calculation.code or "",
                "source_title": source.title if source else "",
                "source_id": (item.source_id if item else None) or (source.source_id if source else ""),
                "source_page": item.page if item else "",
                "evidence_origin": origin,
                "evidence_strength": strength,
                "evidence_snippet": item.text_snippet if item else "",
            })
    return tuple(rows)


def build_archive_explorer(
    archive: SynthexArchive, *, include_quarantined: bool = False,
) -> ArchiveExplorerData:
    """Build every Explorer view from one validated archive without mutation."""
    if not isinstance(archive, SynthexArchive):
        raise TypeError("archive must be a validated SynthexArchive")
    bundle = export_csv_bundle(archive, include_quarantined=include_quarantined)
    return ArchiveExplorerData(
        results=project_results_rows(archive, include_quarantined=include_quarantined),
        materials=_decode_csv(bundle.files["materials.csv"]),
        processes=_decode_csv(bundle.files["processes.csv"]),
        experiments=_decode_csv(bundle.files["experiments.csv"]),
        calculations=_calculation_rows(archive),
        evidence=_decode_csv(bundle.files["evidence.csv"]),
        relationships=tuple({
            "source_id": row.get("subject_id", ""),
            "relation": row.get("predicate", ""),
            "target_id": row.get("object_id", ""),
            "relation_id": row.get("relation_id", ""),
            "evidence_ids": row.get("evidence_ids", ""),
        } for row in _decode_csv(bundle.files["relationships.csv"])),
    )


def _tokens(value: Any) -> set[str]:
    return {item.strip().casefold() for item in str(value or "").split("|") if item.strip()}


def _matches_selected(row: Mapping[str, Any], field: str, selected: Iterable[str]) -> bool:
    choices = {str(item).casefold() for item in selected}
    if not choices:
        return True
    value = row.get(field, "")
    if field == "material_names":
        material_tokens = {
            *_tokens(value),
            *_tokens(row.get("material_formulas")),
            *_tokens(row.get("material_ids")),
        }
        return bool(material_tokens & choices)
    return str(value or "").casefold() in choices


def _as_bool(value: Any) -> bool:
    return value is True or str(value).casefold() == "true"


def filter_results(
    rows: Iterable[Mapping[str, Any]], filters: ExplorerFilters | None = None,
) -> tuple[dict[str, Any], ...]:
    """Apply exact field filters and a bounded local text search."""
    selected = filters or ExplorerFilters()
    query = selected.search.strip().casefold()
    search_fields = ("material_names", "material_formulas", "metric", "reaction", "product", "evidence_snippet")
    filtered = []
    for source_row in rows:
        row = dict(source_row)
        if any(not _matches_selected(row, field, getattr(selected, field)) for field in FILTER_FIELDS):
            continue
        if selected.estimated is not None and _as_bool(row.get("estimated")) is not selected.estimated:
            continue
        if query and not any(query in str(row.get(field, "")).casefold() for field in search_fields):
            continue
        filtered.append(row)
    return tuple(sorted(filtered, key=lambda row: str(row.get("record_id", ""))))


def filter_options(rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Return only filter choices actually present in projected archive rows."""
    material_values: set[str] = set()
    options = {field: set() for field in FILTER_FIELDS}
    for row in rows:
        for field in FILTER_FIELDS:
            value = row.get(field)
            if value in (None, ""):
                continue
            if field == "material_names":
                material_values.update(item.strip() for item in str(value).split("|") if item.strip())
            else:
                options[field].add(str(value))
        material_values.update(item.strip() for item in str(row.get("material_formulas", "")).split("|") if item.strip())
        material_values.update(item.strip() for item in str(row.get("material_ids", "")).split("|") if item.strip())
    options["material_names"] = material_values
    return {field: tuple(sorted(values, key=str.casefold)) for field, values in options.items()}
