from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.explorer import build_archive_explorer

MIN_RESEARCH_BATCH = 10
MAX_BATCH_PAPERS = 20


def validate_batch_size(count: int) -> None:
    """Validate the UI batch size without changing single-paper support."""
    if count < 1:
        raise ValueError("Select at least one PDF.")
    if count > MAX_BATCH_PAPERS:
        raise ValueError(
            f"A single Synthex batch currently supports up to {MAX_BATCH_PAPERS} PDFs. "
            "Split larger literature sets into multiple batches."
        )


def combined_result_rows(
    archives: Iterable[SynthexArchive],
    *,
    include_quarantined: bool = False,
) -> list[dict[str, Any]]:
    """Project multiple validated archives into one researcher-facing result set.

    Each PDF is still extracted and validated independently. This function only combines
    the already-built local archive views, preserving source/title/DOI/page fields on rows.
    """
    rows: list[dict[str, Any]] = []
    for archive in archives:
        explorer = build_archive_explorer(
            archive,
            include_quarantined=include_quarantined,
        )
        rows.extend(dict(row) for row in explorer.results)
    return rows


def batch_source_summary(archives: Iterable[SynthexArchive]) -> list[dict[str, Any]]:
    """Small per-paper summary used by the batch UI and tests."""
    output: list[dict[str, Any]] = []
    for archive in archives:
        source = archive.sources[0] if archive.sources else None
        output.append(
            {
                "archive_id": archive.metadata.archive_id,
                "domain": archive.metadata.domain,
                "title": getattr(source, "title", None),
                "doi": getattr(source, "doi", None),
                "materials": len(archive.materials),
                "experiments": len(archive.experiments),
                "calculations": len(archive.calculations),
            }
        )
    return output
