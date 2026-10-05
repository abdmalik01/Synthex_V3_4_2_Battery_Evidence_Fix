"""Scientific admission and device-stack rules for Photovoltaics V1."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Literal

from synthex_platform.core.models import Measurement

from .draft_models import DraftDevice


PVMeasurementRole = Literal["process_parameter", "result"]


@dataclass(frozen=True)
class PVPropertySpec:
    role: PVMeasurementRole
    unit_family: str
    required_conditions: tuple[str, ...] = ()
    modalities: tuple[Literal["experimental", "computational"], ...] = ("experimental",)


@dataclass(frozen=True)
class PVAdmissionDecision:
    admitted: bool
    reason: str


PV_PROPERTIES: dict[str, PVPropertySpec] = {
    # Device performance.
    "power_conversion_efficiency": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance")),
    "open_circuit_voltage": PVPropertySpec("result", "voltage", ("illumination_spectrum", "irradiance")),
    "short_circuit_current_density": PVPropertySpec("result", "current_density", ("illumination_spectrum", "irradiance")),
    "short_circuit_current": PVPropertySpec("result", "current", ("illumination_spectrum", "irradiance")),
    "fill_factor": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance")),
    "maximum_power": PVPropertySpec("result", "power", ("illumination_spectrum", "irradiance")),
    "voltage_at_maximum_power": PVPropertySpec("result", "voltage", ("illumination_spectrum", "irradiance")),
    "stabilized_power_conversion_efficiency": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance")),
    "swept_power_conversion_efficiency": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance")),
    "initial_power_conversion_efficiency": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance")),
    "aged_power_conversion_efficiency": PVPropertySpec("result", "percent", ("illumination_spectrum", "irradiance", "aging_time")),
    "current_density": PVPropertySpec("result", "current_density"),
    "voltage": PVPropertySpec("result", "voltage"),
    # Spectral response.
    "external_quantum_efficiency": PVPropertySpec("result", "percent", ("wavelength",)),
    "incident_photon_to_current_efficiency": PVPropertySpec("result", "percent", ("wavelength",)),
    # Stability.
    "retained_efficiency": PVPropertySpec("result", "percent", ("aging_time",)),
    "degradation_rate": PVPropertySpec("result", "rate"),
    "t80": PVPropertySpec("result", "time", ("aging_protocol", "temperature", "atmosphere")),
    "t90": PVPropertySpec("result", "time", ("aging_protocol", "temperature", "atmosphere")),
    # Computational outputs. These names intentionally cannot be used for
    # experimental measurements, even when their numerical units coincide.
    "calculated_bandgap": PVPropertySpec("result", "energy", (), ("computational",)),
    "calculated_absorption_coefficient": PVPropertySpec("result", "inverse_length", (), ("computational",)),
    "carrier_effective_mass": PVPropertySpec("result", "mass_ratio", (), ("computational",)),
    "defect_formation_energy": PVPropertySpec("result", "energy", (), ("computational",)),
    "simulated_power_conversion_efficiency": PVPropertySpec("result", "percent", (), ("computational",)),
    "simulated_open_circuit_voltage": PVPropertySpec("result", "voltage", (), ("computational",)),
    "predicted_short_circuit_current_density": PVPropertySpec("result", "current_density", (), ("computational",)),
    "simulated_fill_factor": PVPropertySpec("result", "percent", (), ("computational",)),
    # A scalar integral reported from an EQE spectrum is not an EQE point or Jsc.
    "eqe_integrated_current_density": PVPropertySpec("result", "current_density", ("spectral_range",)),
    # Device and measurement context retained as explicit coordinates.
    "active_area": PVPropertySpec("process_parameter", "area"),
    "aperture_area": PVPropertySpec("process_parameter", "area"),
    "irradiance": PVPropertySpec("process_parameter", "irradiance"),
    "measurement_temperature": PVPropertySpec("process_parameter", "temperature"),
    "scan_rate": PVPropertySpec("process_parameter", "scan_rate"),
    "aging_time": PVPropertySpec("process_parameter", "time"),
    # Fabrication context.
    "processing_temperature": PVPropertySpec("process_parameter", "temperature"),
    "processing_time": PVPropertySpec("process_parameter", "time"),
    "film_thickness": PVPropertySpec("process_parameter", "length"),
    "solution_concentration": PVPropertySpec("process_parameter", "concentration"),
    "spin_speed": PVPropertySpec("process_parameter", "rotation_rate"),
}


_ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "percent": frozenset({"%"}),
    "voltage": frozenset({"v", "mv"}),
    "current_density": frozenset({"ma/cm2", "ma/cm^2", "a/m2", "a/m^2"}),
    "current": frozenset({"a", "ma", "ua", "µa", "μa"}),
    "power": frozenset({"w", "mw", "uw", "µw", "μw"}),
    "rate": frozenset({"%/h", "%/day", "1/h", "h^-1", "1/day", "day^-1"}),
    "time": frozenset({"s", "min", "h", "hr", "day", "days"}),
    "area": frozenset({"cm2", "cm^2", "mm2", "mm^2", "m2", "m^2"}),
    "irradiance": frozenset({"mw/cm2", "mw/cm^2", "w/m2", "w/m^2"}),
    "temperature": frozenset({"k", "°c", "c"}),
    "scan_rate": frozenset({"v/s", "mv/s"}),
    "length": frozenset({"m", "mm", "um", "µm", "μm", "nm"}),
    "concentration": frozenset({"m", "mol/l", "mm", "mg/ml", "wt%", "%"}),
    "rotation_rate": frozenset({"rpm"}),
    "energy": frozenset({"ev", "mev"}),
    "inverse_length": frozenset({"cm^-1", "1/cm", "m^-1", "1/m"}),
    "mass_ratio": frozenset({"m0", "m_e", "me", "dimensionless"}),
}

_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_ALLOWED_LAYER_ROLES = frozenset({
    "substrate", "transparent_electrode", "etl", "absorber", "htl", "electrode",
    "buffer", "interconnect", "encapsulation", "other",
})


def _unit_key(unit: str | None) -> str:
    return re.sub(r"\s+", "", unit or "").casefold().replace("²", "2")


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _value_supported(measurement: Measurement) -> bool:
    raw = re.sub(r"\s+", " ", measurement.raw_value or "").strip().casefold()
    return bool(raw) and any(
        evidence.verbatim_match is True
        and evidence.source_type.value in {"text", "table", "supplementary"}
        and raw in re.sub(r"\s+", " ", evidence.text_snippet or "").strip().casefold()
        and (
            evidence.page is not None
            or evidence.original_source_type == "official_source_data_workbook"
        )
        and (evidence.locator or evidence.table_id)
        for evidence in measurement.evidence
    )


def photovoltaics_admission_decision(
    measurement: Measurement,
    *,
    role: PVMeasurementRole,
    modality: Literal["experimental", "computational"] = "experimental",
) -> PVAdmissionDecision:
    spec = PV_PROPERTIES.get(measurement.property)
    if spec is None:
        return PVAdmissionDecision(False, "unknown_photovoltaics_property")
    if spec.role != role:
        return PVAdmissionDecision(False, f"property_role_mismatch_{spec.role}")
    if modality not in spec.modalities:
        return PVAdmissionDecision(False, f"property_not_allowed_for_{modality}")
    if not measurement.raw_value:
        return PVAdmissionDecision(False, "missing_raw_value")
    if not _value_supported(measurement):
        return PVAdmissionDecision(False, "no_value_specific_verbatim_evidence")
    if not _numeric(measurement.value):
        return PVAdmissionDecision(False, "numeric_value_required")
    if not any(
        math.isclose(float(match.group()), float(measurement.value), rel_tol=1e-8, abs_tol=1e-12)
        for match in _NUMBER.finditer(measurement.raw_value)
    ):
        return PVAdmissionDecision(False, "parsed_value_mismatch")
    if _unit_key(measurement.unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return PVAdmissionDecision(False, f"invalid_unit_for_{spec.unit_family}")
    if measurement.normalized_unit and _unit_key(measurement.normalized_unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return PVAdmissionDecision(False, f"invalid_normalized_unit_for_{spec.unit_family}")

    scientific_type = measurement.conditions.get("scientific_type")
    allowed = (
        {"reported_process_parameter"}
        if role == "process_parameter"
        else {"model_prediction", "simulation_result"}
        if modality == "computational"
        else {"reported_measurement", "reported_derived_metric"}
    )
    if scientific_type not in allowed:
        return PVAdmissionDecision(False, "invalid_or_missing_scientific_type")
    missing = [key for key in spec.required_conditions if measurement.conditions.get(key) in (None, "")]
    if missing:
        return PVAdmissionDecision(False, f"missing_required_condition_{missing[0]}")
    return PVAdmissionDecision(True, "admitted")


def photovoltaics_device_decision(device: DraftDevice) -> PVAdmissionDecision:
    if device.device_type not in {"solar_cell", "photovoltaic_module"}:
        return PVAdmissionDecision(False, "invalid_photovoltaic_device_type")
    if not device.layer_stack:
        return PVAdmissionDecision(False, "missing_layer_stack")
    ordered = sorted(device.layer_stack, key=lambda layer: layer.sequence_index)
    if [layer.sequence_index for layer in ordered] != list(range(len(ordered))):
        return PVAdmissionDecision(False, "noncontiguous_layer_sequence")
    if len({layer.sequence_index for layer in ordered}) != len(ordered):
        return PVAdmissionDecision(False, "duplicate_layer_sequence")
    if any(layer.role.casefold() not in _ALLOWED_LAYER_ROLES for layer in ordered):
        return PVAdmissionDecision(False, "unknown_layer_role")
    if not any(layer.role.casefold() == "absorber" for layer in ordered):
        return PVAdmissionDecision(False, "missing_absorber_layer")
    return PVAdmissionDecision(True, "admitted")
