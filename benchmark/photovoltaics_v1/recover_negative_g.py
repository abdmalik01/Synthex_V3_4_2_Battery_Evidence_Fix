"""Source-locked photocatalysis negative routing control for PV-NEG-G."""

from __future__ import annotations

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftSource, ExtractedDocument
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle

from .case_common import load_locked


def recover_negative_g():
    source_path, gold, _ = load_locked("negative_g_source_lock.json")
    bundle = build_source_bundle(source_path, enable_ocr=False, include_figures=False)
    if len(bundle.pages) != gold["source"]["page_count"]:
        raise ValueError("PV-NEG-G page count differs from source lock")
    text = bundle.page_marked_text()
    router = DomainRouter()
    first = router.route_text(text)
    second = router.route_text(text)
    source = gold["source"]
    probe = assemble_archive(
        ExtractedDocument(source=DraftSource(
            title=source["title"], doi=source["doi"], url=source["url"],
            year=source["year"], authors=source["authors"],
        ), domain_values={"case_id": gold["case_id"], "provider_invoked": False}),
        domain="photovoltaics",
        model="negative_control_no_provider",
    )
    return probe, first, second, text
