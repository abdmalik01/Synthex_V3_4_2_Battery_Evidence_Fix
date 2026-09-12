from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel

from .battery_models import BatteryDocument, BatteryEvidence


_UNICODE_TRANSLATION = str.maketrans({
    "\u00a0": " ",
    "\u2007": " ",
    "\u202f": " ",
    "\u2212": "-",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00ad": "",
})


def normalize_evidence_text(value: str) -> str:
    """Normalize PDF typography without reducing paraphrases to false matches."""
    text = unicodedata.normalize("NFKC", value).translate(_UNICODE_TRANSLATION)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def marked_text_pages(source_text: str) -> dict[int, str]:
    marker = re.compile(r"(?:^|\n)--- PAGE (\d+) ---\n")
    matches = list(marker.finditer(source_text))
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_text)
        pages[int(match.group(1))] = source_text[match.end():end]
    return pages


def verify_evidence(evidence: BatteryEvidence, source_text: str, pages: dict[int, str] | None = None) -> bool:
    """Record whether an evidence snippet is a normalized verbatim source substring."""
    snippet = evidence.text_snippet
    if not snippet or not snippet.strip():
        evidence.verbatim_match = False
        return False
    page_map = pages if pages is not None else marked_text_pages(source_text)
    if evidence.page is not None and page_map:
        candidate = page_map.get(evidence.page)
        if candidate is None:
            evidence.verbatim_match = False
            return False
    else:
        candidate = source_text
    evidence.verbatim_match = normalize_evidence_text(snippet) in normalize_evidence_text(candidate)
    return evidence.verbatim_match


def _evidence_objects(value: Any):
    if isinstance(value, BatteryEvidence):
        yield value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _evidence_objects(getattr(value, field_name))
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _evidence_objects(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _evidence_objects(item)


def verify_battery_evidence(doc: BatteryDocument, source_text: str) -> BatteryDocument:
    """Verify every evidence object in-place while preserving its raw snippet and locator fields."""
    pages = marked_text_pages(source_text)
    for evidence in _evidence_objects(doc):
        verify_evidence(evidence, source_text, pages)
    doc._source_text = source_text
    return doc
