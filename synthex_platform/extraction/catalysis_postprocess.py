"""Scientific guardrails and deterministic admission policy for Catalysis V1."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .catalysis_evidence import (
    SUPPORTED_EVIDENCE_ORIGINS,
    evidence_is_value_specific,
    verify_catalysis_document_evidence,
    normalize_catalysis_evidence_text,
)
from .catalysis_models import CatalysisDocument, CatalysisEvidence, collect_stage1_warnings
from .source_context import SourceBundle


# Tolerance is only for floating-point representations immediately above 100;
# it is not a scientific correction and the reported value is never changed.
PERCENT_TOLERANCE = 1e-6

PRODUCT_SPECIFIC = {
    "faradaic_efficiency", "product_selectivity", "partial_current_density",
    "product_formation_rate", "selectivity", "yield",
}
PERCENT_PROPERTIES = {
    "faradaic_efficiency", "product_selectivity", "selectivity", "yield", "conversion",
    "carbon_balance", "retention", "degradation_efficiency", "removal_efficiency",
    "cod_removal", "color_removal", "turbidity_removal",
}
NORMALIZATION_REQUIRED = {
    "current_density", "partial_current_density", "mass_activity", "specific_activity",
    "turnover_frequency", "reaction_rate", "activity", "productivity", "product_formation_rate",
}
POTENTIAL_REFERENCE_REQUIRED = {"onset_potential", "half_wave_potential"}
_PHOTOCATALYSIS = re.compile(r"\bphotocatal(?:ysis|ytic|yst)\w*\b", flags=re.I)


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str | None = None


def _explicit_photocatalysis(document: CatalysisDocument) -> bool:
    """Recognize only explicitly labelled heterogeneous photocatalysis.

    This is a narrow V1.1 scope promotion, not a general deferred-subtype bypass.
    A source title or the experiment's reported reaction must literally identify
    photocatalysis/photocatalytic chemistry.
    """
    if "heterogeneous_catalysis" not in document.paper_types or not document.heterogeneous_experiments:
        return False
    texts = [document.source.title or ""]
    texts.extend(item.reaction.reported_reaction or "" for item in document.heterogeneous_experiments)
    return any(_PHOTOCATALYSIS.search(text) for text in texts)


def _promote_explicit_photocatalysis_scope(document: CatalysisDocument) -> None:
    if document.scope_status == "deferred_subtype" and _explicit_photocatalysis(document):
        document.scope_status = "supported"
        document.semantic_warnings = list(dict.fromkeys([
            *document.semantic_warnings,
            "photocatalysis_supported_v1_1",
        ]))


def _link_explicit_referenced_catalyst_evidence(document: CatalysisDocument) -> None:
    """Carry exact child evidence to an explicitly named referenced catalyst.

    This repairs provenance linkage only. It never creates a catalyst, changes
    ownership, or treats a scientific value as evidence of an unnamed material.
    """
    catalysts = {item.local_id: item for item in document.catalysts}
    experiments = {
        item.experiment_id: item
        for item in [*document.heterogeneous_experiments, *document.electrocatalysis_experiments]
    }

    def link(local_id: str | None, evidence: list[CatalysisEvidence]) -> None:
        catalyst = catalysts.get(local_id or "")
        if catalyst is None or catalyst.ownership != "focal_work" or not catalyst.reported_name:
            return
        name = normalize_catalysis_evidence_text(catalyst.reported_name)
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        known = {item.model_dump_json(exclude_none=True) for item in catalyst.evidence}
        for item in evidence:
            snippet = normalize_catalysis_evidence_text(item.text_snippet or "")
            serialized = item.model_dump_json(exclude_none=True)
            if pattern.search(snippet) and serialized not in known:
                catalyst.evidence.append(item.model_copy(deep=True))
                known.add(serialized)

    for experiment in experiments.values():
        evidence = [*experiment.evidence]
        for metric in experiment.metrics:
            evidence.extend(metric.evidence)
        link(experiment.catalyst_ref, evidence)
    for stability in document.stability_tests:
        parent = experiments.get(stability.experiment_ref or "")
        local_id = stability.catalyst_state_ref or (parent.catalyst_ref if parent else None)
        evidence = [*stability.evidence]
        if stability.retained_metric is not None:
            evidence.extend(stability.retained_metric.evidence)
        link(local_id, evidence)


def decide_quantitative_admission(
    *,
    ownership: str,
    property_name: str,
    raw_value: str | None,
    value: float | None,
    unit: str | None,
    evidence: list[CatalysisEvidence],
    scope_status: str,
    product: str | None = None,
    reactant: str | None = None,
    normalization_kind: str | None = None,
    potential_reference: str | None = None,
    derived: bool = False,
    unresolved_conflict: bool = False,
    semantic_invalid: bool = False,
) -> AdmissionDecision:
    if scope_status != "supported":
        return AdmissionDecision(False, "unsupported_v1_subtype")
    if ownership != "focal_work":
        return AdmissionDecision(False, f"ownership_{ownership}")
    if derived:
        return AdmissionDecision(False, "derived_value_not_reported")
    if unresolved_conflict:
        return AdmissionDecision(False, "condition_conflict")
    if semantic_invalid:
        return AdmissionDecision(False, "schema_invalid")
    if property_name in PERCENT_PROPERTIES and unit == "%" and value is not None and value > 100 + PERCENT_TOLERANCE:
        return AdmissionDecision(False, "schema_invalid")
    if property_name in PRODUCT_SPECIFIC and not product:
        return AdmissionDecision(False, "missing_product")
    if property_name == "conversion" and not reactant:
        return AdmissionDecision(False, "schema_invalid")
    if property_name in NORMALIZATION_REQUIRED and normalization_kind in {None, "unknown"}:
        return AdmissionDecision(False, "normalization_basis_unknown")
    if property_name == "turnover_frequency" and normalization_kind != "site_count":
        return AdmissionDecision(False, "incompatible_unit_basis")
    if potential_reference == "unknown" or (
        property_name in POTENTIAL_REFERENCE_REQUIRED and potential_reference is None
    ):
        return AdmissionDecision(False, "missing_potential_reference")
    if any(item.original_source_type == "figure_digitized" or item.estimated for item in evidence):
        return AdmissionDecision(False, "estimated_digitized")
    if any(item.original_source_type not in SUPPORTED_EVIDENCE_ORIGINS for item in evidence):
        return AdmissionDecision(False, "unsupported_visual_origin")
    if not any(evidence_is_value_specific(item, raw_value, value) for item in evidence):
        return AdmissionDecision(False, "no_value_specific_evidence")
    return AdmissionDecision(True)


def collect_stage2_warnings(document: CatalysisDocument) -> list[str]:
    warnings = list(collect_stage1_warnings(document))
    for experiment in document.heterogeneous_experiments:
        for metric in experiment.metrics:
            if metric.property in PERCENT_PROPERTIES and metric.unit == "%" and metric.value is not None and metric.value > 100 + PERCENT_TOLERANCE:
                warnings.append(f"{experiment.experiment_id}.{metric.property}: percentage_greater_than_100")
            if metric.property == "turnover_frequency" and (metric.normalization_basis is None or metric.normalization_basis.kind != "site_count"):
                warnings.append(f"{experiment.experiment_id}.turnover_frequency: site_count_basis_required")
    for experiment in document.electrocatalysis_experiments:
        for metric in experiment.metrics:
            if metric.property in PERCENT_PROPERTIES and metric.unit == "%" and metric.value is not None and metric.value > 100 + PERCENT_TOLERANCE:
                warnings.append(f"{experiment.experiment_id}.{metric.property}: percentage_greater_than_100")
    return list(dict.fromkeys(warnings))


def postprocess_catalysis_document(
    document: CatalysisDocument,
    source_text: str = "",
    source_bundle: SourceBundle | None = None,
) -> tuple[CatalysisDocument, list[str]]:
    _promote_explicit_photocatalysis_scope(document)
    _link_explicit_referenced_catalyst_evidence(document)
    verify_catalysis_document_evidence(document, source_text, source_bundle)
    warnings = list(dict.fromkeys([*document.semantic_warnings, *collect_stage2_warnings(document)]))
    potentials = []
    for experiment in document.electrocatalysis_experiments:
        potentials.append(experiment.controlled_potential)
        potentials.extend(metric.potential for metric in experiment.metrics)
    potentials.extend(item.operating_potential for item in document.stability_tests)
    # There is intentionally no reference-electrode conversion engine in V1.
    # Extractor-labelled deterministic conversions cannot become canonical.
    for potential in (item for item in potentials if item is not None):
        if potential.conversion_status == "deterministic":
            potential.converted_potential = None
            potential.converted_reference = None
            potential.conversion_status = "rejected"
            warnings.append("deterministic_potential_conversion_rejected_no_auditable_implementation")
    warnings = list(dict.fromkeys(warnings))
    document.semantic_warnings = warnings
    return document, warnings
