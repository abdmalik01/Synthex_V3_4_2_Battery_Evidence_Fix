"""Deterministic scientific-admission policy for Corrosion V1.

This module performs no provider calls. It decides whether one extracted corrosion
metric is eligible for canonical archive admission after schema validation and
evidence verification.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corrosion_models import CorrosionMetric
from .corrosion_units import corrosion_metric_unit_is_compatible


_POTENTIAL_PROPERTIES = {
    "corrosion_potential",
    "pitting_potential",
    "repassivation_potential",
    "breakdown_potential",
}
_EIS_PROPERTIES = {
    "charge_transfer_resistance",
    "solution_resistance",
    "coating_resistance",
    "pore_resistance",
    "protective_layer_resistance",
    "film_resistance",
    "oxide_resistance",
    "cpe_parameter",
    "cpe_exponent",
    "double_layer_capacitance",
    "coating_capacitance",
    "warburg_parameter",
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
    equivalent_circuit: str | None = None,
    condition_properties: set[str] | None = None,
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

    if metric.data_kind == "fitted_parameter" and not equivalent_circuit:
        return CorrosionAdmissionDecision(False, "missing_equivalent_circuit_context")

    if not corrosion_metric_unit_is_compatible(metric.property, metric.quantity.unit):
        return CorrosionAdmissionDecision(False, "incompatible_gravimetric_unit_category")

    if metric.property in {"inhibition_efficiency", "protection_efficiency"} and not treatment_present:
        return CorrosionAdmissionDecision(False, "missing_linked_treatment")

    if experiment_type == "weight_loss":
        if metric.property in {"initial_mass", "final_mass", "mass_loss"}:
            if metric.data_kind != "reported_measurement":
                return CorrosionAdmissionDecision(False, "invalid_gravimetric_data_kind")
        if metric.property in {
            "corrosion_rate", "penetration_rate", "inhibition_efficiency", "protection_efficiency"
        } and metric.data_kind != "derived_metric":
            return CorrosionAdmissionDecision(False, "invalid_gravimetric_data_kind")
        if metric.property in {
            "corrosion_rate", "penetration_rate", "inhibition_efficiency", "protection_efficiency"
        }:
            available = condition_properties or set()
            if "exposure_time" not in available:
                return CorrosionAdmissionDecision(False, "missing_exposure_time")
            if not ({"medium", "electrolyte"} & available):
                return CorrosionAdmissionDecision(False, "missing_environment_context")

    return CorrosionAdmissionDecision(True, None)
