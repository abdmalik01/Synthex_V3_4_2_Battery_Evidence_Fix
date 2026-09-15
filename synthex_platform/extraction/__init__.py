from .domain_extractor import DomainGeminiExtractor
from .assembler import assemble_archive
from .draft_models import ExtractedDocument
from .router import DomainRoute, DomainRouter
from .battery_models import BatteryDocument
from .battery_extractor import BatteryGeminiExtractor
from .battery_assembler import assemble_battery_archive
from .pipeline import SynthexExtractionPipeline
from .source_context import SourceBundle, SourceMetadata, SourcePageContext, build_source_bundle, compact_source_context, has_prompt_source_context
from .catalysis_models import CatalysisDocument
from .catalysis_extractor import CatalysisGeminiExtractor, CatalysisStructuredExtractionValidationError
from .catalysis_assembler import assemble_catalysis_archive
from .corrosion_models import CorrosionDocument
from .corrosion_admission import CorrosionAdmissionDecision, decide_corrosion_metric_admission
from .corrosion_evidence import verify_corrosion_document_evidence, verify_corrosion_evidence_item

# Compatibility defaults for offline/unit-test construction via ``object.__new__``.
# Normal runtime initialization still overwrites these on each extractor instance.
for _extractor_cls in (DomainGeminiExtractor, BatteryGeminiExtractor, CatalysisGeminiExtractor):
    if not hasattr(_extractor_cls, "requested_model"):
        _extractor_cls.requested_model = None
    if not hasattr(_extractor_cls, "fallback_models"):
        _extractor_cls.fallback_models = None
    if not hasattr(_extractor_cls, "provider_mode"):
        _extractor_cls.provider_mode = "production"
    if not hasattr(_extractor_cls, "last_provider_audit"):
        _extractor_cls.last_provider_audit = {}

__all__ = [
    "DomainGeminiExtractor", "assemble_archive", "ExtractedDocument",
    "DomainRoute", "DomainRouter", "BatteryDocument", "BatteryGeminiExtractor",
    "assemble_battery_archive", "SynthexExtractionPipeline", "SourceBundle",
    "SourceMetadata", "SourcePageContext", "build_source_bundle", "compact_source_context",
    "has_prompt_source_context",
    "CatalysisDocument", "CatalysisGeminiExtractor", "CatalysisStructuredExtractionValidationError",
    "assemble_catalysis_archive", "CorrosionDocument",
    "CorrosionAdmissionDecision", "decide_corrosion_metric_admission",
    "verify_corrosion_document_evidence", "verify_corrosion_evidence_item",
]
