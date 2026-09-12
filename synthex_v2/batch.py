from __future__ import annotations
from copy import deepcopy
from .models import SensorRecord, PaperInfo


def stamp_source(record: SensorRecord) -> SensorRecord:
    """Copy paper-level provenance onto each sample for safe batch aggregation."""
    title = record.paper.title
    doi = record.paper.doi
    for sample in record.samples:
        if not sample.source_paper_title:
            sample.source_paper_title = title
        if not sample.source_doi:
            sample.source_doi = doi
    return record


def merge_records(records: list[SensorRecord]) -> SensorRecord:
    """Merge records without losing each sample's paper provenance."""
    merged_samples = []
    notes = []
    for record in records:
        r = stamp_source(deepcopy(record))
        merged_samples.extend(r.samples)
        notes.extend(r.extraction_notes)
    return SensorRecord(
        paper=PaperInfo(title=f"Batch extraction — {len(records)} paper(s)"),
        samples=merged_samples,
        extraction_notes=notes,
    )
