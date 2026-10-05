"""Scientific admission rules for Thermoelectrics V1."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

from synthex_platform.core.models import Measurement


TEMeasurementRole = Literal["process_parameter", "result"]


@dataclass(frozen=True)
class TEPropertySpec:
    role: TEMeasurementRole
    unit_family: str
    scientific_types: tuple[str, ...]
    requires_temperature: bool = False
    requires_orientation: bool = False


@dataclass(frozen=True)
class TEAdmissionDecision:
    admitted: bool
    reason: str


TE_PROPERTIES: dict[str, TEPropertySpec] = {
    "seebeck_coefficient": TEPropertySpec(
        "result", "seebeck", ("reported_measurement",), True, True
    ),
    "electrical_conductivity": TEPropertySpec(
        "result", "electrical_conductivity", ("reported_measurement",), True, True
    ),
    "electrical_resistivity": TEPropertySpec(
        "result", "electrical_resistivity", ("reported_measurement",), True, True
    ),
    "total_thermal_conductivity": TEPropertySpec(
        "result", "thermal_conductivity", ("reported_measurement", "reported_derived_metric"), True, True
    ),
    "lattice_thermal_conductivity": TEPropertySpec(
        "result", "thermal_conductivity", ("reported_derived_metric",), True, True
    ),
    "electronic_thermal_conductivity": TEPropertySpec(
        "result", "thermal_conductivity", ("reported_derived_metric",), True, True
    ),
    "power_factor": TEPropertySpec(
        "result", "power_factor", ("reported_derived_metric",), True, True
    ),
    "zt": TEPropertySpec(
        "result", "dimensionless", ("reported_derived_metric",), True, True
    ),
    "carrier_concentration": TEPropertySpec(
        "result", "carrier_concentration", ("reported_measurement", "reported_derived_metric"), True, True
    ),
    "carrier_mobility": TEPropertySpec(
        "result", "carrier_mobility", ("reported_measurement", "reported_derived_metric"), True, True
    ),
    "carrier_effective_mass": TEPropertySpec(
        "result", "effective_mass", ("reported_measurement",), False, True
    ),
    "reaction_temperature": TEPropertySpec("process_parameter", "temperature", ("reported_process_parameter",)),
    "reaction_time": TEPropertySpec("process_parameter", "time", ("reported_process_parameter",)),
    "annealing_temperature": TEPropertySpec("process_parameter", "temperature", ("reported_process_parameter",)),
    "annealing_time": TEPropertySpec("process_parameter", "time", ("reported_process_parameter",)),
    "purification_temperature": TEPropertySpec("process_parameter", "temperature", ("reported_process_parameter",)),
    "purification_time": TEPropertySpec("process_parameter", "time", ("reported_process_parameter",)),
    "sintering_temperature": TEPropertySpec("process_parameter", "temperature", ("reported_process_parameter",)),
    "sintering_time": TEPropertySpec("process_parameter", "time", ("reported_process_parameter",)),
    "sintering_pressure": TEPropertySpec("process_parameter", "pressure", ("reported_process_parameter",)),
    "relative_density": TEPropertySpec("process_parameter", "percent", ("reported_process_parameter",)),
}


_ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "seebeck": frozenset({"v/k", "mv/k", "uv/k"}),
    "electrical_conductivity": frozenset({"s/m", "s/cm", "ks/m"}),
    "electrical_resistivity": frozenset({"ohm*m", "ohm*cm", "ohmcm", "ω*m", "ω*cm"}),
    "thermal_conductivity": frozenset({"w/m/k", "w/(m*k)", "w*m^-1*k^-1"}),
    "power_factor": frozenset({"w/m/k2", "w/m/k^2", "uw/cm/k2", "uw/cm/k^2"}),
    "dimensionless": frozenset({"dimensionless", "1"}),
    "carrier_concentration": frozenset({"1/cm3", "cm^-3", "1/m3", "m^-3"}),
    "carrier_mobility": frozenset({"cm2/v/s", "cm^2/v/s", "m2/v/s", "m^2/v/s"}),
    "effective_mass": frozenset({"m_e", "me", "m0"}),
    "temperature": frozenset({"k", "c", "°c"}),
    "time": frozenset({"s", "min", "h", "hr"}),
    "pressure": frozenset({"pa", "kpa", "mpa", "gpa", "torr"}),
    "percent": frozenset({"%"}),
}

_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _unit_key(unit: str | None) -> str:
    return (
        re.sub(r"\s+", "", unit or "")
        .casefold()
        .replace("²", "2")
        .replace("³", "3")
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("·", "*")
        .replace("−", "-")
    )


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _value_supported(measurement: Measurement) -> bool:
    raw = re.sub(r"\s+", " ", measurement.raw_value or "").strip().casefold()
    return bool(raw) and any(
        evidence.verbatim_match is True
        and evidence.source_type.value in {"text", "table", "supplementary", "computation"}
        and "caption" not in (evidence.original_source_type or "").casefold()
        and raw in re.sub(r"\s+", " ", evidence.text_snippet or "").strip().casefold()
        and (
            evidence.page is not None
            or evidence.original_source_type == "official_source_data_workbook"
        )
        and (evidence.locator or evidence.table_id)
        for evidence in measurement.evidence
    )


def thermoelectrics_admission_decision(
    measurement: Measurement,
    *,
    role: TEMeasurementRole,
    modality: str = "experimental",
) -> TEAdmissionDecision:
    if role == "result" and modality not in {"experimental", "computational"}:
        return TEAdmissionDecision(False, "invalid_thermoelectrics_modality")
    spec = TE_PROPERTIES.get(measurement.property)
    if spec is None:
        return TEAdmissionDecision(False, "unknown_thermoelectrics_property")
    if spec.role != role:
        return TEAdmissionDecision(False, f"property_role_mismatch_{spec.role}")
    if not measurement.raw_value:
        return TEAdmissionDecision(False, "missing_raw_value")
    if not _value_supported(measurement):
        return TEAdmissionDecision(False, "no_value_specific_verbatim_evidence")
    if not _numeric(measurement.value):
        return TEAdmissionDecision(False, "numeric_value_required")
    raw_for_numbers = measurement.raw_value.replace(",", "").replace("−", "-")
    if not any(
        math.isclose(float(match.group()), float(measurement.value), rel_tol=1e-8, abs_tol=1e-12)
        for match in _NUMBER.finditer(raw_for_numbers)
    ):
        return TEAdmissionDecision(False, "parsed_value_mismatch")
    if _unit_key(measurement.unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return TEAdmissionDecision(False, f"invalid_unit_for_{spec.unit_family}")
    if (
        measurement.normalized_unit
        and _unit_key(measurement.normalized_unit) not in _ALLOWED_UNITS[spec.unit_family]
    ):
        return TEAdmissionDecision(False, f"invalid_normalized_unit_for_{spec.unit_family}")

    scientific_type = measurement.conditions.get("scientific_type")
    if modality == "computational":
        if scientific_type != "calculated":
            return TEAdmissionDecision(False, "computational_output_must_be_calculated")
    elif scientific_type not in spec.scientific_types:
        return TEAdmissionDecision(False, "invalid_or_missing_scientific_type")
    if spec.requires_temperature:
        temperature = measurement.conditions.get("temperature")
        if not _numeric(temperature):
            return TEAdmissionDecision(False, "missing_or_invalid_temperature")
        if _unit_key(measurement.conditions.get("temperature_unit")) != "k":
            return TEAdmissionDecision(False, "temperature_must_be_kelvin")
    if spec.requires_orientation and not measurement.conditions.get("measurement_orientation"):
        return TEAdmissionDecision(False, "missing_measurement_orientation")

    if measurement.property == "seebeck_coefficient":
        sign = measurement.conditions.get("seebeck_sign")
        expected = "positive" if float(measurement.value) > 0 else "negative" if float(measurement.value) < 0 else "zero"
        if sign != expected:
            return TEAdmissionDecision(False, "seebeck_sign_mismatch")
        if measurement.conditions.get("carrier_type") not in {"p-type", "n-type", "mixed", "not_reported"}:
            return TEAdmissionDecision(False, "missing_or_invalid_carrier_type")
        if measurement.conditions.get("absolute_value") is True:
            return TEAdmissionDecision(False, "absolute_seebeck_not_canonical")

    if measurement.property in {
        "total_thermal_conductivity",
        "lattice_thermal_conductivity",
        "electronic_thermal_conductivity",
        "power_factor",
        "zt",
    } and not measurement.conditions.get("derivation_basis"):
        return TEAdmissionDecision(False, "missing_derivation_basis")

    return TEAdmissionDecision(True, "admitted")
