"""Deterministic scientific-admission policy for Corrosion V1.

This module performs no provider calls. It decides whether one extracted corrosion
metric is eligible for canonical archive admission after schema validation and
evidence verification.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corrosion_models import CorrosionMetric


_POTENTIAL_PROPERTIES = {
    "corrosion_potential",
    "pitting_potential",
    "repassivation_potential",
    "breakdown_potential",
}
_EIS_PROPERTIES = {
    "charge_transfer_resistance",
    "solution_resistance",
    "cpe_parameter",
    "double_layer_capacitance",
}


@dataclass(frozen=True)
class CorrosionAdmissionDecision:
    admitted: bool
    reason: str | None = None


def decide_corrosion_metric_admission(
    metric: CorrosionMetric,
    *,
    scope_status: str,
    experiment_type: str,
    reference_electrode: str | None,
    treatment_present: bool,
    unresolved_conflict: bool,
) -> CorrosionAdmissionDecision:
    """Apply the bounded Corrosion V1 canonical-admission contract.

    Rules are intentionally conservative. This function never derives values,
    converts reference electrodes, repairs units, or infers missing conditions.
    """
    if scope_status != "supported":
        return CorrosionAdmissionDecision(False, "unsupported_scope")
    if metric.ownership != "focal_work":
        return CorrosionAdmissionDecision(False, f"ownership_{metric.ownership}")
    if metric.quantity.value is None:
        return CorrosionAdmissionDecision(False, "non_numeric_or_unparsed_value")
    if not metric.quantity.raw_value.strip():
        return CorrosionAdmissionDecision(False, "missing_raw_value")
    if unresolved_conflict:
        return CorrosionAdmissionDecision(False, "unresolved_condition_conflict")
    if not any(
        evidence.verbatim_match is True
        and evidence.text_snippet
        and evidence.original_source_type not in {"figure_reported", "unknown"}
        for evidence in metric.evidence
    ):
        return CorrosionAdmissionDecision(False, "no_verified_value_specific_evidence")

    if metric.property in _POTENTIAL_PROPERTIES and not reference_electrode:
        return CorrosionAdmissionDecision(False, "missing_reference_electrode")

    if metric.property in _EIS_PROPERTIES and experiment_type != "eis":
        return CorrosionAdmissionDecision(False, "eis_metric_outside_eis_experiment")

    if metric.property == "polarization_resistance" and experiment_type == "eis":
        return CorrosionAdmissionDecision(False, "polarization_resistance_misclassified_as_eis")

    if metric.property in {"inhibition_efficiency", "protection_efficiency"} and not treatment_present:
        return CorrosionAdmissionDecision(False, "missing_linked_treatment")

    return CorrosionAdmissionDecision(True, None)
