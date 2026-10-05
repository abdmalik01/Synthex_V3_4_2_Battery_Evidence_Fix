"""Scientific admission and specimen-architecture rules for Membranes V1."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Literal

from synthex_platform.core.models import Measurement

from .draft_models import DraftDevice


MembraneMeasurementRole = Literal["process_parameter", "result"]


@dataclass(frozen=True)
class MembranePropertySpec:
    role: MembraneMeasurementRole
    unit_family: str
    modalities: tuple[str, ...]
    required_conditions: tuple[str, ...] = ()
    scientific_types: tuple[str, ...] = ("reported_measurement",)


@dataclass(frozen=True)
class MembraneAdmissionDecision:
    admitted: bool
    reason: str


MEMBRANE_PROPERTIES: dict[str, MembranePropertySpec] = {
    # Gas separation. Permeability and permeance deliberately have disjoint units.
    "gas_permeability": MembranePropertySpec(
        "result", "gas_permeability", ("gas_separation",),
        ("species", "test_mode", "temperature", "temperature_unit", "pressure_kind"),
    ),
    "gas_permeance": MembranePropertySpec(
        "result", "gas_permeance", ("gas_separation",),
        ("species", "test_mode", "temperature", "temperature_unit", "pressure_kind"),
    ),
    "ideal_selectivity": MembranePropertySpec(
        "result", "dimensionless", ("gas_separation",),
        ("species_pair", "test_mode", "temperature", "temperature_unit"),
        ("reported_derived_metric",),
    ),
    "mixed_gas_selectivity": MembranePropertySpec(
        "result", "dimensionless", ("gas_separation",),
        ("species_pair", "test_mode", "temperature", "temperature_unit"),
        ("reported_measurement", "reported_derived_metric"),
    ),
    "separation_factor": MembranePropertySpec(
        "result", "dimensionless", ("pervaporation",),
        ("species_pair", "test_mode", "temperature", "temperature_unit"),
        ("reported_measurement", "reported_derived_metric"),
    ),
    "activation_energy_of_permeance": MembranePropertySpec(
        "result", "energy_per_mole", ("gas_separation",),
        ("species", "temperature_range"), ("reported_derived_metric",),
    ),
    "estimated_selective_layer_thickness": MembranePropertySpec(
        "result", "length", ("gas_separation",),
        ("species", "estimation_basis"), ("reported_derived_metric",),
    ),
    # Computational membrane transport. These properties are admitted only
    # from CalculationRecords and retain the source's velocity/diffusivity
    # quantities instead of being relabeled as experimental permeability.
    "calculated_membrane_permeability_coefficient": MembranePropertySpec(
        "result", "velocity", ("computational_transport",),
        ("species", "temperature", "temperature_unit", "simulation_method", "lipid_composition"),
        ("simulation_result",),
    ),
    "calculated_apparent_diffusion_coefficient": MembranePropertySpec(
        "result", "diffusivity", ("computational_transport",),
        ("species", "temperature", "temperature_unit", "simulation_method", "lipid_composition"),
        ("simulation_result",),
    ),
    # Liquid separation / filtration.
    "liquid_flux": MembranePropertySpec(
        "result", "liquid_flux", ("liquid_separation", "filtration", "pervaporation"),
        ("feed", "test_mode", "pressure_kind"),
    ),
    "liquid_permeance": MembranePropertySpec(
        "result", "liquid_permeance", ("liquid_separation", "filtration"),
        ("feed", "test_mode", "pressure_kind"),
    ),
    "solute_rejection": MembranePropertySpec(
        "result", "percent_or_fraction", ("liquid_separation", "filtration"),
        ("solute", "feed_concentration", "test_mode", "pressure_kind"),
    ),
    "retention": MembranePropertySpec(
        "result", "percent_or_fraction", ("liquid_separation", "filtration"),
        ("solute", "feed_concentration", "test_mode", "pressure_kind"),
    ),
    "initial_flux": MembranePropertySpec(
        "result", "mass_flux", ("filtration",),
        ("feed", "test_mode", "transmembrane_pressure"),
    ),
    "fouled_flux": MembranePropertySpec(
        "result", "mass_flux", ("filtration",),
        ("feed", "foulant", "test_mode", "transmembrane_pressure"),
    ),
    "recovered_flux": MembranePropertySpec(
        "result", "mass_flux", ("filtration",),
        ("feed", "foulant", "cleaning_method", "test_mode", "transmembrane_pressure"),
    ),
    "flux_recovery_ratio": MembranePropertySpec(
        "result", "percent", ("filtration",),
        ("foulant", "cleaning_method"), ("reported_derived_metric",),
    ),
    "relative_flux_reduction": MembranePropertySpec(
        "result", "percent", ("filtration",),
        ("foulant",), ("reported_derived_metric",),
    ),
    # Fabrication coordinates. These remain process parameters, never performance.
    "filler_loading": MembranePropertySpec(
        "process_parameter", "percent", ("fabrication",), scientific_types=("reported_process_parameter",),
    ),
    "polymer_concentration": MembranePropertySpec(
        "process_parameter", "percent", ("fabrication",), scientific_types=("reported_process_parameter",),
    ),
    "casting_gap": MembranePropertySpec(
        "process_parameter", "length", ("fabrication",), scientific_types=("reported_process_parameter",),
    ),
    "drying_temperature": MembranePropertySpec(
        "process_parameter", "temperature", ("fabrication",), scientific_types=("reported_process_parameter",),
    ),
    "drying_time": MembranePropertySpec(
        "process_parameter", "time", ("fabrication",), scientific_types=("reported_process_parameter",),
    ),
}


_ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "gas_permeability": frozenset({"barrer", "mol*m/(m2*s*pa)", "mol*m/(m^2*s*pa)"}),
    "gas_permeance": frozenset({
        "gpu", "mol/(m2*s*pa)", "mol/(m^2*s*pa)",
        "10^2m_stp3*m^-2*h^-1*bar^-1", "10^2m_stp^3*m^-2*h^-1*bar^-1",
        "10^2m_stp3m^-2h^-1bar^-1", "10^2m_stp^3m^-2h^-1bar^-1",
    }),
    "dimensionless": frozenset({"dimensionless", "1"}),
    "energy_per_mole": frozenset({"kj/mol", "kjmol^-1"}),
    "velocity": frozenset({"cm/s"}),
    "diffusivity": frozenset({"10^-6cm2/s", "10^-6cm^2/s"}),
    "length": frozenset({"m", "mm", "um", "µm", "μm", "nm"}),
    "liquid_flux": frozenset({"lmh", "l/m2/h", "l/m^2/h", "kg/m2/h", "kg/m^2/h", "mol/m2/s", "mol/m^2/s"}),
    "liquid_permeance": frozenset({"l/m2/h/bar", "l/m^2/h/bar", "kg/m2/h/bar", "kg/m^2/h/bar"}),
    "mass_flux": frozenset({"g/m2/s", "g/m^2/s", "kg/m2/h", "kg/m^2/h"}),
    "percent_or_fraction": frozenset({"%", "fraction", "dimensionless", "1"}),
    "percent": frozenset({"%"}),
    "temperature": frozenset({"k", "c", "°c"}),
    "time": frozenset({"s", "min", "h", "hr", "day", "days"}),
}

_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_MISSING_VALUE = re.compile(r"^(?:n/?a|not available|not reported|[-–—])$", re.IGNORECASE)
_ALLOWED_DEVICE_TYPES = frozenset({"membrane_specimen"})
_ALLOWED_LAYER_ROLES = frozenset({
    "substrate", "support", "porous_support", "interlayer", "membrane_body",
    "selective_layer", "protective_layer", "filler_additive",
})
_ALLOWED_MODALITIES = frozenset({"gas_separation", "liquid_separation", "filtration", "pervaporation"})


def _unit_key(unit: str | None) -> str:
    return (
        re.sub(r"\s+", "", unit or "").casefold()
        .replace("²", "2").replace("³", "3")
        .replace("·", "*").replace("−", "-")
    )


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _value_supported(measurement: Measurement) -> bool:
    raw = re.sub(r"\s+", " ", measurement.raw_value or "").strip().casefold()
    return bool(raw) and any(
        evidence.verbatim_match is True
        and evidence.source_type.value in {"text", "table", "supplementary"}
        and "caption" not in (evidence.original_source_type or "").casefold()
        and raw in re.sub(r"\s+", " ", evidence.text_snippet or "").strip().casefold()
        and evidence.page is not None
        and (evidence.locator or evidence.table_id)
        for evidence in measurement.evidence
    )


def membranes_admission_decision(
    measurement: Measurement,
    *,
    role: MembraneMeasurementRole,
    modality: str,
) -> MembraneAdmissionDecision:
    spec = MEMBRANE_PROPERTIES.get(measurement.property)
    if spec is None:
        return MembraneAdmissionDecision(False, "unknown_membrane_property")
    if spec.role != role:
        return MembraneAdmissionDecision(False, f"property_role_mismatch_{spec.role}")
    if modality not in spec.modalities:
        return MembraneAdmissionDecision(False, f"property_not_allowed_for_{modality}")
    if not measurement.raw_value:
        return MembraneAdmissionDecision(False, "missing_raw_value")
    if _MISSING_VALUE.match(measurement.raw_value.strip()):
        return MembraneAdmissionDecision(False, "non_numeric_missing_value_token")
    if not _value_supported(measurement):
        return MembraneAdmissionDecision(False, "no_value_specific_verbatim_table_evidence")
    if not _numeric(measurement.value):
        return MembraneAdmissionDecision(False, "numeric_value_required")
    raw_for_numbers = measurement.raw_value.replace(",", "").replace("−", "-")
    if not any(
        math.isclose(float(match.group()), float(measurement.value), rel_tol=1e-8, abs_tol=1e-12)
        for match in _NUMBER.finditer(raw_for_numbers)
    ):
        return MembraneAdmissionDecision(False, "parsed_value_mismatch")
    if _unit_key(measurement.unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return MembraneAdmissionDecision(False, f"invalid_unit_for_{spec.unit_family}")
    if measurement.normalized_unit and _unit_key(measurement.normalized_unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return MembraneAdmissionDecision(False, f"invalid_normalized_unit_for_{spec.unit_family}")
    if measurement.conditions.get("scientific_type") not in spec.scientific_types:
        return MembraneAdmissionDecision(False, "invalid_or_missing_scientific_type")
    missing = [key for key in spec.required_conditions if measurement.conditions.get(key) in (None, "")]
    if missing:
        return MembraneAdmissionDecision(False, f"missing_required_condition_{missing[0]}")

    test_mode = measurement.conditions.get("test_mode")
    if measurement.property == "ideal_selectivity" and test_mode != "pure_gas":
        return MembraneAdmissionDecision(False, "ideal_selectivity_requires_pure_gas_basis")
    if measurement.property == "mixed_gas_selectivity" and test_mode != "mixed_gas":
        return MembraneAdmissionDecision(False, "mixed_gas_selectivity_requires_mixture_basis")
    if measurement.property == "gas_permeability" and _unit_key(measurement.unit) == "gpu":
        return MembraneAdmissionDecision(False, "gpu_is_permeance_not_permeability")
    if measurement.property == "gas_permeance" and _unit_key(measurement.unit) == "barrer":
        return MembraneAdmissionDecision(False, "barrer_is_permeability_not_permeance")
    return MembraneAdmissionDecision(True, "admitted")


def membranes_device_decision(device: DraftDevice) -> MembraneAdmissionDecision:
    if device.device_type not in _ALLOWED_DEVICE_TYPES:
        return MembraneAdmissionDecision(False, "invalid_membrane_device_type")
    if device.configuration.get("membrane_modality") not in _ALLOWED_MODALITIES:
        return MembraneAdmissionDecision(False, "missing_or_invalid_membrane_modality")
    if not device.layer_stack:
        return MembraneAdmissionDecision(False, "missing_membrane_architecture")
    ordered = sorted(device.layer_stack, key=lambda layer: layer.sequence_index)
    sequence = [layer.sequence_index for layer in ordered]
    if sequence != list(range(len(ordered))) or len(set(sequence)) != len(sequence):
        return MembraneAdmissionDecision(False, "noncontiguous_or_duplicate_layer_sequence")
    roles = [layer.role.casefold() for layer in ordered]
    if any(role not in _ALLOWED_LAYER_ROLES for role in roles):
        return MembraneAdmissionDecision(False, "unknown_membrane_layer_role")
    if not ({"membrane_body", "selective_layer"} & set(roles)):
        return MembraneAdmissionDecision(False, "missing_separating_layer")
    if device.configuration.get("architecture_type") == "multilayer_composite":
        if "selective_layer" not in roles or not ({"support", "porous_support", "substrate"} & set(roles)):
            return MembraneAdmissionDecision(False, "multilayer_composite_missing_support_or_selective_layer")
    expected_thickness_names = {
        "membrane_body": "membrane_thickness",
        "selective_layer": "selective_layer_thickness",
        "support": "support_thickness",
        "porous_support": "support_thickness",
        "substrate": "support_thickness",
    }
    for layer in ordered:
        if layer.thickness is None:
            continue
        expected = expected_thickness_names.get(layer.role.casefold())
        if expected and layer.thickness.property != expected:
            return MembraneAdmissionDecision(False, "thickness_scope_role_mismatch")
    return MembraneAdmissionDecision(True, "admitted")
