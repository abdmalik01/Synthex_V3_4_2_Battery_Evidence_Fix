from __future__ import annotations

from pathlib import Path

from .battery_assembler import assemble_battery_archive
from .battery_extractor import BatteryGeminiExtractor
from .domain_extractor import DomainGeminiExtractor
from .router import DomainRoute, DomainRouter
from .source_context import SourceBundle, build_source_bundle
from synthex_platform.retrieval import MetadataEnricher, SerperClient
from synthex_platform.visual.sidecar_store import VisualSidecarStore


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
        ocr_provider=None,
        enable_ocr: bool = True,
        visual_sidecar_store: VisualSidecarStore | None = None,
    ):
        self.router = router or DomainRouter()
        self.api_key = api_key
        self.model = model
        self.search_assisted = search_assisted
        self.find_supplementary = find_supplementary
        self.serper_api_key = serper_api_key
        self.ocr_provider = ocr_provider
        self.enable_ocr = enable_ocr
        self.visual_sidecar_store = visual_sidecar_store or VisualSidecarStore("data/archive")

    def route_text(self, text: str) -> DomainRoute:
        return self.router.route_text(text)

    def extract_text(self, text: str, domain: str = "auto"):
        return self._extract(text, domain=domain, source_bundle=None)

    def build_source_bundle(self, pdf_path: str | Path, *, source_filename: str | None = None) -> SourceBundle:
        return build_source_bundle(
            pdf_path,
            source_filename=source_filename,
            ocr_provider=self.ocr_provider,
            enable_ocr=self.enable_ocr,
            sidecar_store=self.visual_sidecar_store,
        )

    def extract_source_bundle(self, source_bundle: SourceBundle, domain: str = "auto"):
        """Extract one PDF source while retaining its visual and parser context."""
        return self._extract(
            source_bundle.page_marked_text(), domain=domain, source_bundle=source_bundle,
        )

    def _extract(self, text: str, domain: str, source_bundle: SourceBundle | None):
        route = self.router.route_text(text) if domain == "auto" else DomainRoute(
            domain=domain, confidence=1.0, scores={domain: 1.0}, matched_terms={domain: []}, paper_types=[], method="user_selected"
        )
        if route.domain == "batteries":
            extractor = BatteryGeminiExtractor(api_key=self.api_key, model=self.model)
            draft = extractor.extract_text(text, source_bundle=source_bundle)
            if source_bundle is not None:
                parser = source_bundle.primary_native_parser()
                draft._pdf_parser = parser
                draft.source.pdf_text_parser = parser
            archive = assemble_battery_archive(draft, model=extractor.model)
        else:
            # Generic manifest-driven path. Gas sensing remains more mature in the legacy V2 UI.
            extractor = DomainGeminiExtractor(api_key=self.api_key, model=self.model)
            archive = extractor.extract_text(text, route.domain, source_bundle=source_bundle)
        if source_bundle is not None:
            if archive.sources:
                archive.sources[0].checksum = source_bundle.source.source_checksum
            for payload in archive.domain_payloads:
                if payload.domain == route.domain:
                    payload.values["source_context"] = source_bundle.parser_metadata()
        if self.search_assisted:
            client = SerperClient(api_key=self.serper_api_key)
            archive = MetadataEnricher(client=client).enrich_archive(
                archive, find_supplementary=self.find_supplementary
            )
        return route, archive

    def extract_pdf(self, pdf_path: str | Path, domain: str = "auto"):
        return self.extract_source_bundle(self.build_source_bundle(pdf_path), domain=domain)
