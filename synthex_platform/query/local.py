from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from synthex_platform.core.archive import SynthexArchive


@dataclass
class Query:
    domain: str | None = None
    element: str | None = None
    formula_contains: str | None = None
    property: str | None = None
    target: str | None = None
    year_min: int | None = None
    year_max: int | None = None


def _properties(archive: SynthexArchive) -> set[str]:
    result = set()
    for e in archive.experiments:
        result.update(m.property for m in e.outputs)
    for c in archive.calculations:
        result.update(m.property for m in c.outputs)
    return result


def matches(archive: SynthexArchive, q: Query) -> bool:
    if q.domain and archive.metadata.domain != q.domain:
        return False
    if q.element and not any(q.element in m.elements for m in archive.materials):
        return False
    if q.formula_contains and not any(q.formula_contains.lower() in (m.formula or "").lower() for m in archive.materials):
        return False
    if q.property and q.property not in _properties(archive):
        return False
    if q.target and not any((e.target or "").lower() == q.target.lower() for e in archive.experiments):
        return False
    years = [s.year for s in archive.sources if s.year]
    if q.year_min and years and max(years) < q.year_min:
        return False
    if q.year_max and years and min(years) > q.year_max:
        return False
    return True


def search(archives: Iterable[SynthexArchive], query: Query) -> list[SynthexArchive]:
    return [a for a in archives if matches(a, query)]
