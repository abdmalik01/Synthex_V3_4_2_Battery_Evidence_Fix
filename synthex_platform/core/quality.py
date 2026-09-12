from __future__ import annotations

from .archive import SynthexArchive
from .models import Evidence, Measurement


def _measurements(archive: SynthexArchive) -> list[Measurement]:
    out: list[Measurement] = []
    for p in archive.processes:
        out.extend(p.parameters)
    for e in archive.experiments:
        out.extend(e.conditions)
        out.extend(e.outputs)
    for c in archive.calculations:
        out.extend(c.parameters)
        out.extend(c.outputs)
    return out


def _evidence_bearing_records(archive: SynthexArchive):
    records = []
    records.extend(archive.materials)
    records.extend(archive.devices)
    records.extend(archive.processes)
    records.extend(archive.experiments)
    records.extend(archive.calculations)
    records.extend(archive.relationships)
    return records


def score_archive(archive: SynthexArchive) -> SynthexArchive:
    measurements = _measurements(archive)
    records = _evidence_bearing_records(archive)

    # Provenance is measured across quantitative measurements and scientific records,
    # not only Measurement.evidence. This avoids reporting zero provenance when an
    # experiment/process has page-level evidence shared by its child measurements.
    provenance_flags = [bool(m.evidence) for m in measurements]
    provenance_flags += [bool(getattr(r, "evidence", [])) for r in records]
    if provenance_flags:
        archive.quality.provenance_coverage = sum(provenance_flags) / len(provenance_flags)

    unit_candidates = [m for m in measurements if m.value is not None and m.unit]
    if unit_candidates:
        normalized = sum(m.normalized_value is not None and bool(m.normalized_unit) for m in unit_candidates)
        archive.quality.unit_normalization_coverage = normalized / len(unit_candidates)

    # Generic structural completeness is deliberately conservative. Domain-specific
    # assemblers may override this using subtype-aware expectations.
    blocks = {
        "source": bool(archive.sources),
        "entity": bool(archive.materials or archive.devices),
        "activity": bool(archive.processes or archive.experiments or archive.calculations),
        "property": bool(measurements),
        "domain_payload": bool(archive.domain_payloads),
    }
    archive.quality.completeness = sum(blocks.values()) / len(blocks)

    confidences = [ev.confidence for m in measurements for ev in m.evidence if ev.confidence is not None]
    for record in records:
        confidences.extend(ev.confidence for ev in getattr(record, "evidence", []) if ev.confidence is not None)
    if confidences:
        archive.quality.extraction_confidence = sum(confidences) / len(confidences)

    archive.quality.validation_status = "schema_validated"
    return archive
