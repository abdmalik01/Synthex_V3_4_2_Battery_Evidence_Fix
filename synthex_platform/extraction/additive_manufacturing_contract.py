"""Scientific admission contract for process-centric Additive Manufacturing records."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Literal

from synthex_platform.core.models import Measurement

from .mechanical_contract import MECHANICAL_PROPERTIES, mechanical_admission_decision


AMMeasurementRole = Literal["process_parameter", "result"]


@dataclass(frozen=True)
class AMPropertySpec:
    role: AMMeasurementRole
    unit_family: str
    categorical: bool = False


@dataclass(frozen=True)
class AMAdmissionDecision:
    admitted: bool
    reason: str


AM_PROPERTIES: dict[str, AMPropertySpec] = {
    # Build and post-processing coordinates.
    "laser_power": AMPropertySpec("process_parameter", "power"),
    "electron_beam_power": AMPropertySpec("process_parameter", "power"),
    "scan_speed": AMPropertySpec("process_parameter", "speed"),
    "hatch_spacing": AMPropertySpec("process_parameter", "length"),
    "layer_thickness": AMPropertySpec("process_parameter", "length"),
    "spot_size": AMPropertySpec("process_parameter", "length"),
    "beam_diameter": AMPropertySpec("process_parameter", "length"),
    "powder_feed_rate": AMPropertySpec("process_parameter", "mass_flow"),
    "wire_feed_rate": AMPropertySpec("process_parameter", "speed"),
    "preheat_temperature": AMPropertySpec("process_parameter", "temperature"),
    "post_process_temperature": AMPropertySpec("process_parameter", "temperature"),
    "post_process_time": AMPropertySpec("process_parameter", "time"),
    "chamber_oxygen": AMPropertySpec("process_parameter", "concentration"),
    "rotation_angle": AMPropertySpec("process_parameter", "angle"),
    "linear_energy_density": AMPropertySpec("process_parameter", "energy_per_length"),
    "surface_energy_density": AMPropertySpec("process_parameter", "energy_per_area"),
    "volumetric_energy_density": AMPropertySpec("process_parameter", "energy_per_volume"),
    "scan_strategy": AMPropertySpec("process_parameter", "categorical", categorical=True),
    "build_orientation": AMPropertySpec("process_parameter", "categorical", categorical=True),
    "shielding_gas": AMPropertySpec("process_parameter", "categorical", categorical=True),
    "machine_model": AMPropertySpec("process_parameter", "categorical", categorical=True),
    # AM quality, defect, geometry, microstructure, and productivity outcomes.
    "relative_density": AMPropertySpec("result", "percent"),
    "absolute_density": AMPropertySpec("result", "density"),
    "porosity": AMPropertySpec("result", "percent"),
    "void_fraction": AMPropertySpec("result", "percent"),
    "defect_fraction": AMPropertySpec("result", "percent"),
    "lack_of_fusion_fraction": AMPropertySpec("result", "percent"),
    "keyhole_porosity": AMPropertySpec("result", "percent"),
    "surface_roughness_ra": AMPropertySpec("result", "length"),
    "surface_roughness_rz": AMPropertySpec("result", "length"),
    "melt_pool_width": AMPropertySpec("result", "length"),
    "melt_pool_depth": AMPropertySpec("result", "length"),
    "grain_size": AMPropertySpec("result", "length"),
    "cell_spacing": AMPropertySpec("result", "length"),
    "phase_fraction": AMPropertySpec("result", "percent"),
    "texture_coefficient": AMPropertySpec("result", "dimensionless"),
    "dimensional_error": AMPropertySpec("result", "length"),
    "build_rate": AMPropertySpec("result", "volume_rate"),
}


_ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "power": frozenset({"w", "kw"}),
    "speed": frozenset({"mm/s", "m/s", "mm/min", "m/min"}),
    "length": frozenset({"m", "mm", "um", "µm", "μm"}),
    "mass_flow": frozenset({"g/s", "g/min", "kg/h"}),
    "temperature": frozenset({"k", "°c", "c"}),
    "time": frozenset({"s", "min", "h", "hr"}),
    "concentration": frozenset({"ppm", "%", "vol%"}),
    "angle": frozenset({"°", "deg", "degree", "degrees"}),
    "energy_per_length": frozenset({"j/mm", "j/m"}),
    "energy_per_area": frozenset({"j/mm2", "j/mm^2", "j/m2", "j/m^2"}),
    "energy_per_volume": frozenset({"j/mm3", "j/mm^3", "j/cm3", "j/cm^3"}),
    "percent": frozenset({"%", "vol%"}),
    "density": frozenset({"kg/m3", "kg/m^3", "g/cm3", "g/cm^3"}),
    "dimensionless": frozenset({"", "1", "dimensionless"}),
    "volume_rate": frozenset({"mm3/s", "mm^3/s", "cm3/h", "cm^3/h"}),
    "categorical": frozenset({""}),
}

_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _unit_key(unit: str | None) -> str:
    return re.sub(r"\s+", "", unit or "").casefold()


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _raw_matches_numeric_value(raw: str, value: float) -> bool:
    numbers = [float(match.group()) for match in _NUMBER.finditer(raw)]
    if any(math.isclose(number, value, rel_tol=1e-8, abs_tol=1e-12) for number in numbers):
        return True
    normalized = re.sub(r"\s+", " ", raw.strip().casefold())
    return value == 1.0 and normalized in {"one", "one hour", "an hour"}


def _value_supported(measurement: Measurement) -> bool:
    raw = (measurement.raw_value or "").strip().casefold()
    return bool(raw) and any(
        evidence.verbatim_match is True
        and evidence.source_type.value in {"text", "table", "supplementary"}
        and raw in (evidence.text_snippet or "").strip().casefold()
        and evidence.page is not None
        and (evidence.locator or evidence.table_id or evidence.figure_id)
        for evidence in measurement.evidence
    )


def additive_manufacturing_admission_decision(
    measurement: Measurement, *, role: AMMeasurementRole,
    modality: Literal["experimental", "computational"] = "experimental",
) -> AMAdmissionDecision:
    """Admit only reported, source-grounded AM coordinates and outcomes.

    Mechanical outcomes in AM papers reuse the Mechanical contract rather than
    acquiring duplicate AM property identities.
    """
    if role == "result" and measurement.property in MECHANICAL_PROPERTIES:
        decision = mechanical_admission_decision(measurement, modality=modality)
        return AMAdmissionDecision(decision.admitted, decision.reason)

    spec = AM_PROPERTIES.get(measurement.property)
    if spec is None:
        return AMAdmissionDecision(False, "unknown_am_property")
    if spec.role != role:
        return AMAdmissionDecision(False, f"property_role_mismatch_{spec.role}")
    if not measurement.raw_value:
        return AMAdmissionDecision(False, "missing_raw_value")
    if not _value_supported(measurement):
        return AMAdmissionDecision(False, "no_value_specific_verbatim_evidence")

    scientific_type = measurement.conditions.get("scientific_type")
    allowed_types = (
        {"reported_process_parameter", "reported_derived_metric"}
        if role == "process_parameter"
        else {"model_prediction", "simulation_result"}
        if modality == "computational"
        else {"reported_measurement", "reported_derived_metric"}
    )
    if scientific_type not in allowed_types:
        return AMAdmissionDecision(False, "invalid_or_missing_scientific_type")

    if spec.categorical:
        if not isinstance(measurement.value, str) or not measurement.value.strip():
            return AMAdmissionDecision(False, "categorical_value_required")
    else:
        if not _numeric(measurement.value):
            return AMAdmissionDecision(False, "numeric_value_required")
        if not _raw_matches_numeric_value(measurement.raw_value, float(measurement.value)):
            return AMAdmissionDecision(False, "parsed_value_mismatch")

    if _unit_key(measurement.unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return AMAdmissionDecision(False, f"invalid_unit_for_{spec.unit_family}")
    if measurement.normalized_unit and _unit_key(measurement.normalized_unit) not in _ALLOWED_UNITS[spec.unit_family]:
        return AMAdmissionDecision(False, f"invalid_normalized_unit_for_{spec.unit_family}")
    return AMAdmissionDecision(True, "admitted")
