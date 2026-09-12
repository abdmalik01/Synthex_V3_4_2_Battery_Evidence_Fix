from __future__ import annotations

from pathlib import Path

from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text
from .battery_assembler import assemble_battery_archive
from .battery_extractor import BatteryGeminiExtractor
from .domain_extractor import DomainGeminiExtractor
from .router import DomainRoute, DomainRouter
from synthex_platform.retrieval import MetadataEnricher, SerperClient


class SynthexExtractionPipeline:
    """One front door for Synthex V3 literature extraction."""

    def __init__(
        self,
        router: DomainRouter | None = None,
        api_key: str | None = None,
        model: str | None = None,
        serper_api_key: str | None = None,
        search_assisted: bool = False,
        find_supplementary: bool = False,
    ):
        self.router = router or DomainRouter()
        self.api_key = api_key
        self.model = model
        self.search_assisted = search_assisted
        self.find_supplementary = find_supplementary
        self.serper_api_key = serper_api_key

    def route_text(self, text: str) -> DomainRoute:
        return self.router.route_text(text)

    def extract_text(self, text: str, domain: str = "auto"):
        route = self.router.route_text(text) if domain == "auto" else DomainRoute(
            domain=domain, confidence=1.0, scores={domain: 1.0}, matched_terms={domain: []}, paper_types=[], method="user_selected"
        )
        if route.domain == "batteries":
            extractor = BatteryGeminiExtractor(api_key=self.api_key, model=self.model)
            draft = extractor.extract_text(text)
            archive = assemble_battery_archive(draft, model=extractor.model)
        else:
            # Generic manifest-driven path. Gas sensing remains more mature in the legacy V2 UI.
            extractor = DomainGeminiExtractor(api_key=self.api_key, model=self.model)
            archive = extractor.extract_text(text, route.domain)
        if self.search_assisted:
            client = SerperClient(api_key=self.serper_api_key)
            archive = MetadataEnricher(client=client).enrich_archive(
                archive, find_supplementary=self.find_supplementary
            )
        return route, archive

    def extract_pdf(self, pdf_path: str | Path, domain: str = "auto"):
        pages = extract_pages(str(pdf_path))
        text = pages_to_marked_text(pages)
        return self.extract_text(text, domain=domain)
