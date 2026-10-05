"""Source-locked routing and contamination probe for MECH-NEGATIVE-H."""

from __future__ import annotations

import pymupdf

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftSource, ExtractedDocument
from synthex_platform.extraction.router import DomainRouter

from .locked_case import load_locked_case


def recover_negative_h():
    source, gold, _ = load_locked_case("MECH-NEGATIVE-H")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Negative-control PDF page count differs from source lock")
        text = "\n".join(page.get_text() for page in document)
    router = DomainRouter()
    first = router.route_text(text)
    second = router.route_text(text)
    draft = ExtractedDocument(source=DraftSource(
        title=gold["source"]["title"], doi=gold["source"]["doi"],
        url=gold["source"]["url"], year=gold["source"]["year"],
        authors=gold["source"]["authors"],
    ))
    mechanical_probe = assemble_archive(draft, domain="mechanical", model="negative_control_no_provider")
    return mechanical_probe, first, second, text
