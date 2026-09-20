"""Read-only archive scoping for researcher workflows.

One canonical archive architecture is retained.  These models index and filter
archives by explicit session, domain, archive, and source identity without copying
or mutating scientific records.
"""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.export import project_results_rows


CURRENT_EXTRACTION_STATE_KEY = "synthex_current_extraction"
VISUAL_SCOPE_STATE_KEY = "synthex_viz_data_scope"
EXPLORER_DOMAIN_STATE_KEY = "synthex_explorer_domain"
UNKNOWN_LEGACY_DOMAIN = "unknown_legacy"


class DataScope(str, Enum):
    CURRENT_EXTRACTION = "current_extraction"
    SELECTED_SOURCES = "selected_sources"
    CURRENT_DOMAIN = "current_domain"
    CUSTOM_COMBINATION = "custom_combination"
    ENTIRE_ARCHIVE = "entire_archive"


SCOPE_LABELS = {
    DataScope.CURRENT_EXTRACTION: "Current extraction",
    DataScope.SELECTED_SOURCES: "Selected archived papers",
    DataScope.CURRENT_DOMAIN: "Entire selected domain",
    DataScope.CUSTOM_COMBINATION: "Custom combination",
    DataScope.ENTIRE_ARCHIVE: "Entire archive",
}
SCOPE_BY_LABEL = {label: scope for scope, label in SCOPE_LABELS.items()}


THESIS_DOMAINS: tuple[tuple[str, str], ...] = (
    ("batteries", "Batteries"),
    ("catalysis", "Catalysis"),
    ("corrosion", "Corrosion"),
    ("mechanical", "Mechanical / Creep / Fatigue"),
    ("additive_manufacturing", "Additive Manufacturing"),
    ("photovoltaics", "Photovoltaics"),
    ("thermoelectrics", "Thermoelectrics"),
    ("membranes", "Membranes"),
    ("semiconductors", "Semiconductors"),
    ("biomaterials", "Biomaterials"),
)
THESIS_DOMAIN_LABELS = dict(THESIS_DOMAINS)


class CurrentExtraction(BaseModel):
    """Identity of the most recent successful extraction action in one UI session."""

    run_id: str
    archive_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    completed_at: str


class ArchiveQueryContext(BaseModel):
    """Reusable AND-filter context for archive-backed UI and analytics consumers."""

    scope: DataScope
    domain: str | None = None
    archive_ids: frozenset[str] = Field(default_factory=frozenset)
    source_ids: frozenset[str] = Field(default_factory=frozenset)
    run_id: str | None = None
    record_types: frozenset[str] = Field(default_factory=frozenset)
    admissibility: frozenset[str] = Field(default_factory=frozenset)
    properties: frozenset[str] = Field(default_factory=frozenset)


def archive_domain(archive: SynthexArchive) -> str:
    """Return explicit domain metadata, never a filename-derived guess."""
    return archive.metadata.domain or UNKNOWN_LEGACY_DOMAIN


def archive_source_ids(archive: SynthexArchive) -> frozenset[str]:
    return frozenset(source.source_id for source in archive.sources if source.source_id)


def deduplicate_archives(archives: Iterable[SynthexArchive]) -> list[SynthexArchive]:
    """Deduplicate by stable archive ID; later in-session instances take precedence."""
    indexed: dict[str, SynthexArchive] = {}
    for archive in archives:
        indexed[archive.metadata.archive_id] = archive
    return list(indexed.values())


def begin_extraction_action(state: MutableMapping[str, Any]) -> None:
    """Clear current-run identity before work so a failed run cannot look current."""
    state.pop(CURRENT_EXTRACTION_STATE_KEY, None)
    state.pop(EXPLORER_DOMAIN_STATE_KEY, None)
    state[VISUAL_SCOPE_STATE_KEY] = SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]


def record_current_extraction(
    state: MutableMapping[str, Any],
    archives: Iterable[SynthexArchive],
    *,
    run_id: str | None = None,
    completed_at: str | None = None,
) -> CurrentExtraction | None:
    """Replace current extraction identity with one successful action's results."""
    selected = deduplicate_archives(archives)
    if not selected:
        state.pop(CURRENT_EXTRACTION_STATE_KEY, None)
        return None
    record = CurrentExtraction(
        run_id=run_id or f"run-{uuid4().hex}",
        archive_ids=tuple(archive.metadata.archive_id for archive in selected),
        source_ids=tuple(sorted({
            source_id
            for archive in selected
            for source_id in archive_source_ids(archive)
        })),
        domains=tuple(sorted({archive_domain(archive) for archive in selected})),
        completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
    )
    state[CURRENT_EXTRACTION_STATE_KEY] = record.model_dump(mode="json")
    state[VISUAL_SCOPE_STATE_KEY] = SCOPE_LABELS[DataScope.CURRENT_EXTRACTION]
    state.pop(EXPLORER_DOMAIN_STATE_KEY, None)
    if len(record.domains) == 1:
        state[EXPLORER_DOMAIN_STATE_KEY] = record.domains[0]
    return record


def current_extraction_from_state(state: MutableMapping[str, Any]) -> CurrentExtraction | None:
    value = state.get(CURRENT_EXTRACTION_STATE_KEY)
    if not value:
        return None
    try:
        return CurrentExtraction.model_validate(value)
    except Exception:
        return None


def _archive_properties(archive: SynthexArchive) -> set[str]:
    return {
        measurement.property
        for record in (*archive.experiments, *archive.calculations)
        for measurement in record.outputs
    }


def _archive_record_types(archive: SynthexArchive) -> set[str]:
    return {
        *(record.experiment_type for record in archive.experiments),
        *(record.calculation_type for record in archive.calculations),
    }


def select_archives(
    archives: Iterable[SynthexArchive],
    context: ArchiveQueryContext,
    *,
    current_extraction: CurrentExtraction | None = None,
) -> list[SynthexArchive]:
    """Select archives without mutating them or silently broadening an empty scope."""
    candidates = deduplicate_archives(archives)
    archive_ids = context.archive_ids
    source_ids = context.source_ids
    domain = context.domain

    if context.scope == DataScope.CURRENT_EXTRACTION:
        if current_extraction is None:
            return []
        if context.run_id and context.run_id != current_extraction.run_id:
            return []
        archive_ids = frozenset(current_extraction.archive_ids)
    elif context.scope == DataScope.SELECTED_SOURCES and not source_ids:
        return []
    elif context.scope == DataScope.CURRENT_DOMAIN and not domain:
        return []
    elif context.scope == DataScope.CUSTOM_COMBINATION and not (archive_ids or source_ids):
        return []

    selected: list[SynthexArchive] = []
    for archive in candidates:
        if archive_ids and archive.metadata.archive_id not in archive_ids:
            continue
        if source_ids and not (archive_source_ids(archive) & source_ids):
            continue
        if domain and archive_domain(archive) != domain:
            continue
        if context.properties and not (_archive_properties(archive) & set(context.properties)):
            continue
        if context.record_types and not (_archive_record_types(archive) & set(context.record_types)):
            continue
        if context.admissibility:
            statuses = {
                str(row.get("admission_status") or "")
                for row in project_results_rows(archive, include_quarantined=True)
            }
            if not (statuses & set(context.admissibility)):
                continue
        selected.append(archive)
    return selected


def domain_catalog(extra_domains: Iterable[tuple[str, str]] = ()) -> tuple[tuple[str, str], ...]:
    """Return ten thesis domains, optional registered extras, and Unknown / Legacy."""
    output = list(THESIS_DOMAINS)
    known = {slug for slug, _ in output}
    for slug, label in extra_domains:
        if slug not in known and slug != UNKNOWN_LEGACY_DOMAIN:
            output.append((slug, label))
            known.add(slug)
    output.append((UNKNOWN_LEGACY_DOMAIN, "Unknown / Legacy"))
    return tuple(output)


def domain_archive_summaries(
    archives: Iterable[SynthexArchive],
    *,
    extra_domains: Iterable[tuple[str, str]] = (),
) -> list[dict[str, Any]]:
    """Summarize archive hierarchy per domain, including empty configured domains."""
    selected = deduplicate_archives(archives)
    rows: list[dict[str, Any]] = []
    for slug, label in domain_catalog(extra_domains):
        members = [archive for archive in selected if archive_domain(archive) == slug]
        source_keys = {
            source.source_id or f"{archive.metadata.archive_id}:{index}"
            for archive in members
            for index, source in enumerate(archive.sources)
        }
        rows.append({
            "domain": slug,
            "label": label,
            "archive_count": len(members),
            "paper_count": len(source_keys),
            "material_count": sum(len(archive.materials) for archive in members),
            "experiment_count": sum(len(archive.experiments) for archive in members),
            "calculation_count": sum(len(archive.calculations) for archive in members),
            "measurement_count": sum(
                len(record.outputs)
                for archive in members
                for record in (*archive.experiments, *archive.calculations)
            ),
            "latest_archived_run": max(
                (archive.metadata.created_at for archive in members),
                default=None,
            ),
        })
    return rows
