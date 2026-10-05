"""Source-locked routing and contamination probe for AM-NEGATIVE-H."""

from __future__ import annotations

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftSource, ExtractedDocument
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle

from .benchmark_common import load_locked


def recover_negative_h():
    source, gold, _ = load_locked("negative_h_source_lock.json")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    if len(bundle.pages) != gold["source"]["page_count"]:
        raise ValueError("Negative-control PDF page count differs from source lock")
    text = bundle.page_marked_text()
    router = DomainRouter()
    first = router.route_text(text)
    second = router.route_text(text)
    draft = ExtractedDocument(source=DraftSource(
        title=gold["source"]["title"], doi=gold["source"]["doi"],
        url=gold["source"]["url"], year=gold["source"]["year"],
        authors=gold["source"]["authors"],
    ))
    am_probe = assemble_archive(
        draft, domain="additive_manufacturing", model="negative_control_no_provider",
    )
    return am_probe, first, second, text
