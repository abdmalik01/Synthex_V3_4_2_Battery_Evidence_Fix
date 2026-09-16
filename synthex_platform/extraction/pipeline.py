from __future__ import annotations

from pathlib import Path

from .battery_assembler import assemble_battery_archive
from .battery_extractor import BatteryGeminiExtractor
from .catalysis_assembler import assemble_catalysis_archive
from .catalysis_candidate_inventory import (
    CatalysisCoverageRecoverer,
    build_catalysis_candidate_inventory,
    compare_catalysis_candidate_coverage,
    merge_catalysis_coverage_response,
)
from .catalysis_extractor import CatalysisGeminiExtractor
from .corrosion_assembler import assemble_corrosion_archive
from .corrosion_extractor import CorrosionGeminiExtractor
from .domain_extractor import DomainGeminiExtractor
from .router import DomainRoute, DomainRouter
from .source_context import SourceBundle, build_source_bundle
from synthex_platform.core.models import DomainPayload
from synthex_platform.retrieval import MetadataEnricher, SerperClient
from synthex_platform.visual.sidecar_store import VisualSidecarStore


_SCOPE_ORDER = {"supported": 0, "deferred_subtype": 1, "out_of_scope": 2}


def _most_conservative_scope(route_scope: str, document_scope: str) -> str:
    """Prevent a model response from upgrading a router-enforced support boundary."""
    return max((route_scope, document_scope), key=lambda item: _SCOPE_ORDER.get(item, 2))


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
        provider_mode: str = "production",
        fallback_models: list[str] | tuple[str, ...] | None = None,
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
        self.provider_mode = provider_mode
        self.fallback_models = fallback_models
        self.last_extraction_diagnostics: dict = {}
        self.last_provider_audit: dict = {}
        self.last_catalysis_model_outputs: dict[str, str] = {}
        self.last_catalysis_candidate_inventory: list[dict] = []
        self.last_catalysis_candidate_coverage: list[dict] = []
        # Corrosion keeps the source-verified typed draft so benchmark callers can
        # persist a replay artifact before archive assembly. This is intentionally
        # in-memory only during normal production extraction.
        self.last_corrosion_document = None

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
        return self._extract(source_bundle.page_marked_text(), domain=domain, source_bundle=source_bundle)

    def _extract(self, text: str, domain: str, source_bundle: SourceBundle | None):
        self.last_extraction_diagnostics = {}
        self.last_provider_audit = {}
        self.last_catalysis_model_outputs = {}
        self.last_catalysis_candidate_inventory = []
        self.last_catalysis_candidate_coverage = []
        self.last_corrosion_document = None
        route = self.router.route_text(text) if domain == "auto" else DomainRoute(
            domain=domain,
            confidence=1.0,
            scores={domain: 1.0},
            matched_terms={domain: []},
            paper_types=[],
            method="user_selected",
        )

        if route.domain == "batteries":
            extractor = BatteryGeminiExtractor(
                api_key=self.api_key,
                model=self.model,
                provider_mode=self.provider_mode,
                fallback_models=self.fallback_models,
            )
            try:
                draft = extractor.extract_text(text, source_bundle=source_bundle)
            finally:
                self.last_provider_audit = dict(getattr(extractor, "last_provider_audit", {}))
            if source_bundle is not None:
                parser = source_bundle.primary_native_parser()
                draft._pdf_parser = parser
                draft.source.pdf_text_parser = parser
            archive = assemble_battery_archive(draft, model=extractor.model)

        elif route.domain == "catalysis":
            extractor = CatalysisGeminiExtractor(
                api_key=self.api_key,
                model=self.model,
                provider_mode=self.provider_mode,
                fallback_models=self.fallback_models,
            )
            try:
                draft = extractor.extract_text(text, source_bundle=source_bundle)
            finally:
                self.last_extraction_diagnostics = dict(getattr(extractor, "last_diagnostics", {}))
                self.last_provider_audit = dict(getattr(extractor, "last_provider_audit", {}))
                self.last_extraction_diagnostics["provider"] = self.last_provider_audit
                self.last_extraction_diagnostics.setdefault("primary_calls", 1)
                self.last_extraction_diagnostics.setdefault(
                    "schema_repair_calls", self.last_extraction_diagnostics.get("repair_calls", 0)
                )
                self.last_extraction_diagnostics.setdefault("coverage_calls", 0)
                self.last_catalysis_model_outputs = {
                    key: value
                    for key, value in {
                        "raw": getattr(extractor, "last_raw_output", None),
                        "repaired": getattr(extractor, "last_repaired_output", None),
                    }.items()
                    if value
                }
            if source_bundle is not None:
                candidates = build_catalysis_candidate_inventory(source_bundle, extractor.registry)
                coverage = compare_catalysis_candidate_coverage(draft, candidates)
                self.last_catalysis_candidate_inventory = [
                    item.model_dump(mode="json", exclude_none=True) for item in candidates
                ]
                self.last_catalysis_candidate_coverage = [
                    item.model_dump(mode="json", exclude_none=True) for item in coverage
                ]
                coverage_by_id = {item.candidate_id: item for item in coverage}
                uncovered = [
                    item for item in candidates
                    if item.priority == "high" and not coverage_by_id[item.candidate_id].covered
                ]
                self.last_extraction_diagnostics.update({
                    "primary_calls": self.last_extraction_diagnostics["primary_calls"],
                    "schema_repair_calls": self.last_extraction_diagnostics["schema_repair_calls"],
                    "coverage_calls": self.last_extraction_diagnostics["coverage_calls"],
                    "candidates_detected": len(candidates),
                    "high_priority_candidates": sum(item.priority == "high" for item in candidates),
                    "candidates_covered": sum(item.covered for item in coverage),
                    "candidates_sent": len(uncovered),
                    "coverage_candidates_accepted": 0,
                    "coverage_candidates_rejected": 0,
                })
                if uncovered:
                    recoverer = CatalysisCoverageRecoverer(
                        client=extractor.client,
                        model=extractor.model,
                        gateway=getattr(extractor, "_gateway", None),
                    )
                    self.last_extraction_diagnostics["coverage_calls"] = 1
                    self.last_extraction_diagnostics["gemini_calls"] = (
                        self.last_extraction_diagnostics.get("gemini_calls", 0) + 1
                    )
                    try:
                        response = recoverer.recover(draft, uncovered)
                        draft, merge_audit = merge_catalysis_coverage_response(draft, response, uncovered)
                        self.last_extraction_diagnostics.update({
                            "coverage_candidates_accepted": merge_audit["accepted_candidates"],
                            "coverage_candidates_rejected": merge_audit["rejected_candidates"],
                            "coverage_merge": merge_audit,
                        })
                    except Exception as exc:
                        self.last_extraction_diagnostics.update({
                            "coverage_validation_error": f"{type(exc).__name__}: {exc}",
                            "coverage_candidates_rejected": len(uncovered),
                        })
                    finally:
                        if getattr(extractor, "_gateway", None) is not None:
                            self.last_provider_audit = extractor._gateway.audit()
                            self.last_extraction_diagnostics["provider"] = self.last_provider_audit
                        if recoverer.last_raw_output:
                            self.last_catalysis_model_outputs["coverage"] = recoverer.last_raw_output
            effective_scope = _most_conservative_scope(route.scope_status, draft.scope_status)
            if effective_scope != draft.scope_status:
                draft = draft.model_copy(update={
                    "scope_status": effective_scope,
                    "semantic_warnings": [
                        *draft.semantic_warnings,
                        f"scope_constrained_by_router:{route.scope_status}",
                    ],
                })
            if source_bundle is not None:
                draft.source.pdf_text_parser = source_bundle.primary_native_parser()
            archive = assemble_catalysis_archive(
                draft,
                model=extractor.model,
                source_text=text,
                source_bundle=source_bundle,
            )

        elif route.domain == "corrosion":
            extractor = CorrosionGeminiExtractor(
                api_key=self.api_key,
                model=self.model,
                provider_mode=self.provider_mode,
                fallback_models=self.fallback_models,
            )
            try:
                draft = extractor.extract_text(text, source_bundle=source_bundle)
            finally:
                self.last_extraction_diagnostics = dict(getattr(extractor, "last_diagnostics", {}))
                self.last_provider_audit = dict(getattr(extractor, "last_provider_audit", {}))
                self.last_extraction_diagnostics["provider"] = self.last_provider_audit
                self.last_extraction_diagnostics.setdefault("primary_calls", 1)
                self.last_extraction_diagnostics.setdefault(
                    "schema_repair_calls", self.last_extraction_diagnostics.get("repair_calls", 0)
                )
            if source_bundle is not None:
                draft.source.pdf_text_parser = source_bundle.primary_native_parser()
            # ``extract_text`` has already run deterministic source-bundle evidence
            # verification, so this is the exact pre-assembly document suitable for
            # zero-provider benchmark replay.
            self.last_corrosion_document = draft
            archive = assemble_corrosion_archive(
                draft,
                model=extractor.model,
                source_bundle=source_bundle,
            )

        else:
            extractor = DomainGeminiExtractor(
                api_key=self.api_key,
                model=self.model,
                provider_mode=self.provider_mode,
                fallback_models=self.fallback_models,
            )
            try:
                archive = extractor.extract_text(text, route.domain, source_bundle=source_bundle)
            finally:
                self.last_provider_audit = dict(getattr(extractor, "last_provider_audit", {}))

        if source_bundle is not None:
            if archive.sources:
                archive.sources[0].checksum = source_bundle.source.source_checksum
            for payload in archive.domain_payloads:
                if payload.domain == route.domain:
                    payload.values["source_context"] = source_bundle.parser_metadata()

        if self.last_provider_audit:
            archive.domain_payloads.append(DomainPayload(
                domain="llm_provider",
                schema_version="1.0.0",
                tags=["production_failover" if self.provider_mode == "production" else "benchmark_pinned"],
                values=self.last_provider_audit,
            ))

        if self.search_assisted:
            client = SerperClient(api_key=self.serper_api_key)
            archive = MetadataEnricher(client=client).enrich_archive(
                archive,
                find_supplementary=self.find_supplementary,
            )
        return route, archive

    def extract_pdf(self, pdf_path: str | Path, domain: str = "auto"):
        return self.extract_source_bundle(self.build_source_bundle(pdf_path), domain=domain)
