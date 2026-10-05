"""Strict scientific admission rules for the shared Mechanical V1 extractor.

Mechanical records use the generic draft/archive topology.  This module adds the
domain-specific safeguards that topology cannot express by itself: property identity,
unit compatibility, measured/derived/model separation, and curve-point provenance.
It never derives values or converts units.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.scientific_text import normalize_scientific_text
from .mechanical_provider_normalization import is_missing_source_value


class MechanicalScientificType(str, Enum):
    REPORTED_MEASUREMENT = "reported_measurement"
    REPORTED_DERIVED_METRIC = "reported_derived_metric"
    MODEL_PREDICTION = "model_prediction"
    SIMULATION_RESULT = "simulation_result"
    FIGURE_DIGITIZED = "figure_digitized"


class MechanicalSeriesOrigin(str, Enum):
    SOURCE_TABLE = "source_table"
    SUPPLEMENTARY_DATA = "supplementary_data"
    FIGURE_DIGITIZED = "figure_digitized"


class MechanicalMeasurementMetadata(BaseModel):
    """Typed metadata stored in ``Measurement.conditions`` without schema migration."""

    model_config = ConfigDict(extra="ignore")

    scientific_type: MechanicalScientificType
    reported_term: str | None = None
    data_kind: Literal["scalar", "series_point"] = "scalar"
    curve_role: Literal["scalar", "curve_point"] = "scalar"
    series_origin: MechanicalSeriesOrigin | None = None
    series_id: str | None = None


@dataclass(frozen=True)
class MechanicalPropertySpec:
    family: str
    unit_family: str


@dataclass(frozen=True)
class MechanicalAdmissionDecision:
    admitted: bool
    reason: str | None = None


MECHANICAL_PROPERTIES: dict[str, MechanicalPropertySpec] = {
    # Tensile / direct mechanical response.
    "yield_strength": MechanicalPropertySpec("tensile", "stress"),
    "proof_stress": MechanicalPropertySpec("tensile", "stress"),
    "ultimate_tensile_strength": MechanicalPropertySpec("tensile", "stress"),
    "fracture_strength": MechanicalPropertySpec("tensile", "stress"),
    "tensile_strength": MechanicalPropertySpec("tensile", "stress"),
    "elongation": MechanicalPropertySpec("tensile", "strain"),
    "reduction_of_area": MechanicalPropertySpec("tensile", "strain"),
    "youngs_modulus": MechanicalPropertySpec("tensile", "modulus"),
    "poisson_ratio": MechanicalPropertySpec("tensile", "dimensionless"),
    "applied_load": MechanicalPropertySpec("tensile", "force"),
    "stress": MechanicalPropertySpec("tensile", "stress"),
    "strain": MechanicalPropertySpec("tensile", "strain"),
    # Hardness scales are deliberately separate properties.
    "vickers_hardness": MechanicalPropertySpec("hardness", "vickers"),
    "rockwell_hardness": MechanicalPropertySpec("hardness", "rockwell"),
    "brinell_hardness": MechanicalPropertySpec("hardness", "brinell"),
    "indentation_hardness": MechanicalPropertySpec("hardness", "stress"),
    # Creep / stress rupture.
    "creep_strain": MechanicalPropertySpec("creep", "strain"),
    "creep_rate": MechanicalPropertySpec("creep", "rate"),
    "minimum_creep_rate": MechanicalPropertySpec("creep", "rate"),
    "rupture_time": MechanicalPropertySpec("creep", "time"),
    "rupture_strain": MechanicalPropertySpec("creep", "strain"),
    "applied_stress": MechanicalPropertySpec("creep", "stress"),
    "time_to_specific_strain": MechanicalPropertySpec("creep", "time"),
    # Fatigue / crack growth.
    "cycles_to_failure": MechanicalPropertySpec("fatigue", "cycles"),
    "fatigue_strength": MechanicalPropertySpec("fatigue", "stress"),
    "fatigue_limit": MechanicalPropertySpec("fatigue", "stress"),
    "stress_amplitude": MechanicalPropertySpec("fatigue", "stress"),
    "mean_stress": MechanicalPropertySpec("fatigue", "stress"),
    "frequency": MechanicalPropertySpec("fatigue", "frequency"),
    "strain_amplitude": MechanicalPropertySpec("fatigue", "strain"),
    "stress_ratio": MechanicalPropertySpec("fatigue", "dimensionless"),
    "crack_growth_rate": MechanicalPropertySpec("fatigue", "length_per_cycle"),
    # Fracture.
    "fracture_toughness": MechanicalPropertySpec("fracture", "fracture_toughness"),
    "stress_intensity": MechanicalPropertySpec("fracture", "fracture_toughness"),
    "stress_intensity_range": MechanicalPropertySpec("fracture", "fracture_toughness"),
    "j_integral": MechanicalPropertySpec("fracture", "energy_per_area"),
    "ctod": MechanicalPropertySpec("fracture", "length"),
    "impact_energy": MechanicalPropertySpec("fracture", "energy"),
    # Computational elasticity. These may occur in experiments only when directly
    # measured and in calculations only with model/simulation scientific types.
    "elastic_constant_c11": MechanicalPropertySpec("elastic_constant", "modulus"),
    "elastic_constant_c12": MechanicalPropertySpec("elastic_constant", "modulus"),
    "elastic_constant_c13": MechanicalPropertySpec("elastic_constant", "modulus"),
    "elastic_constant_c33": MechanicalPropertySpec("elastic_constant", "modulus"),
    "elastic_constant_c44": MechanicalPropertySpec("elastic_constant", "modulus"),
    "elastic_constant_c66": MechanicalPropertySpec("elastic_constant", "modulus"),
    "bulk_modulus": MechanicalPropertySpec("elastic_modulus", "modulus"),
    "shear_modulus": MechanicalPropertySpec("elastic_modulus", "modulus"),
}


_ALLOWED_UNITS: dict[str, frozenset[str]] = {
    "stress": frozenset({"pa", "kpa", "mpa", "gpa"}),
    "modulus": frozenset({"pa", "kpa", "mpa", "gpa"}),
    "strain": frozenset({"1", "%", "percent", "dimensionless", "microstrain", "ue", "µe"}),
    "dimensionless": frozenset({"", "1", "dimensionless"}),
    "force": frozenset({"n", "kn", "mn"}),
    "time": frozenset({"s", "sec", "min", "h", "hr", "day", "days"}),
    "rate": frozenset({"s^-1", "1/s", "s-1", "h^-1", "1/h", "h-1"}),
    "frequency": frozenset({"hz", "1/s", "s^-1", "rpm"}),
    "cycles": frozenset({"", "cycle", "cycles", "count", "dimensionless"}),
    "length_per_cycle": frozenset({"m/cycle", "mm/cycle", "um/cycle", "µm/cycle"}),
    "fracture_toughness": frozenset({
        "pa*sqrt(m)", "kpa*sqrt(m)", "mpa*sqrt(m)", "gpa*sqrt(m)",
        "pa√m", "kpa√m", "mpa√m", "gpa√m",
    }),
    "energy_per_area": frozenset({"j/m2", "j/m^2", "kj/m2", "kj/m^2"}),
    "length": frozenset({"m", "mm", "um", "µm"}),
    "energy": frozenset({"j", "mj", "kj"}),
    "vickers": frozenset({"hv"}),
    "rockwell": frozenset({"hra", "hrb", "hrc"}),
    "brinell": frozenset({"hb", "hbw"}),
}


def _unit_key(unit: str | None) -> str:
    if unit is None:
        return ""
    value = str(unit).strip().replace("−", "-").replace("·", "*")
    value = re.sub(r"\s+", "", value)
    value = value.replace("²", "2")
    return value.lower()


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_GROUPED_NUMBER = re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)")
_SCIENTIFIC_PRODUCT = re.compile(
    r"(?<![\w.])([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*[×x*]\s*10\s*\^?\s*\{?\s*([-+]?\d+)\s*\}?"
)


def _reported_numbers(raw_value: str) -> list[float]:
    """Parse printed scalars without converting units or deriving other metrics."""
    text = normalize_scientific_text(raw_value, casefold=False)
    text = _GROUPED_NUMBER.sub(lambda match: match.group().replace(",", ""), text)
    numbers = [float(match.group()) for match in _NUMBER.finditer(text)]
    numbers.extend(
        float(match.group(1)) * 10 ** int(match.group(2))
        for match in _SCIENTIFIC_PRODUCT.finditer(text)
    )
    return numbers


def _evidence_supports_value(evidence: Iterable[Evidence], raw_value: str) -> bool:
    needle = re.sub(r"\s+", " ", raw_value).strip().casefold()
    for item in evidence:
        if item.verbatim_match is not True:
            continue
        snippet = re.sub(r"\s+", " ", item.text_snippet or "").strip().casefold()
        if needle and needle in snippet:
            return True
    return False


def mechanical_admission_decision(
    measurement: Measurement,
    *,
    modality: Literal["experimental", "computational"],
) -> MechanicalAdmissionDecision:
    """Decide admission without changing the source measurement."""

    spec = MECHANICAL_PROPERTIES.get(measurement.property)
    if spec is None:
        reason = "ambiguous_hardness_scale" if measurement.property == "hardness" else "unknown_mechanical_property"
        return MechanicalAdmissionDecision(False, reason)

    value = measurement.normalized_value if _numeric(measurement.normalized_value) else measurement.value
    if not _numeric(value):
        return MechanicalAdmissionDecision(False, "non_numeric_value")
    if not measurement.raw_value:
        return MechanicalAdmissionDecision(False, "missing_raw_value")
    if is_missing_source_value(measurement.raw_value) or is_missing_source_value(measurement.value):
        return MechanicalAdmissionDecision(False, "explicit_missing_source_value")

    raw_numbers = _reported_numbers(measurement.raw_value)
    if not raw_numbers:
        return MechanicalAdmissionDecision(False, "raw_value_not_numeric")
    if measurement.value is not None and _numeric(measurement.value):
        if not any(math.isclose(number, float(measurement.value), rel_tol=1e-8, abs_tol=1e-20) for number in raw_numbers):
            return MechanicalAdmissionDecision(False, "parsed_value_mismatch")

    provided_units = [
        candidate for candidate in (measurement.unit, measurement.normalized_unit)
        if candidate is not None
    ]
    if not provided_units:
        provided_units = [None]
    if any(_unit_key(unit) not in _ALLOWED_UNITS[spec.unit_family] for unit in provided_units):
        return MechanicalAdmissionDecision(False, "incompatible_unit")

    try:
        metadata = MechanicalMeasurementMetadata.model_validate(measurement.conditions)
    except ValidationError:
        return MechanicalAdmissionDecision(False, "missing_or_invalid_scientific_type")

    if metadata.scientific_type == MechanicalScientificType.FIGURE_DIGITIZED:
        return MechanicalAdmissionDecision(False, "figure_digitization_not_canonical")
    if modality == "experimental" and metadata.scientific_type in {MechanicalScientificType.MODEL_PREDICTION, MechanicalScientificType.SIMULATION_RESULT}:
        return MechanicalAdmissionDecision(False, "model_prediction_in_experiment")
    if modality == "computational" and metadata.scientific_type not in {MechanicalScientificType.MODEL_PREDICTION, MechanicalScientificType.SIMULATION_RESULT}:
        return MechanicalAdmissionDecision(False, "non_model_result_in_calculation")
    if (metadata.curve_role == "curve_point") != (metadata.data_kind == "series_point"):
        return MechanicalAdmissionDecision(False, "inconsistent_curve_data_kind")

    if metadata.curve_role == "curve_point":
        if metadata.series_origin is None or not metadata.series_id:
            return MechanicalAdmissionDecision(False, "curve_point_missing_source_series_provenance")
        if metadata.series_origin == MechanicalSeriesOrigin.FIGURE_DIGITIZED:
            return MechanicalAdmissionDecision(False, "figure_digitization_not_canonical")

    if not _evidence_supports_value(measurement.evidence, measurement.raw_value):
        return MechanicalAdmissionDecision(False, "measurement_value_not_source_evidenced")

    return MechanicalAdmissionDecision(True)


def mechanical_prompt_contract() -> list[str]:
    """Concise provider-facing rules; returned data are inert until admission passes."""

    return [
        "Use only canonical property keys listed in this manifest; never use generic hardness.",
        "Keep Vickers, Rockwell, Brinell, and indentation hardness distinct; never convert between scales.",
        "Store scientific_type in every output Measurement.conditions as reported_measurement, reported_derived_metric, model_prediction, simulation_result, or figure_digitized; preserve reported_term.",
        "Put model_prediction and simulation_result outputs in calculations, never experiments; do not derive unreported quantities.",
        "Preserve reported temperature, strain rate, orientation, loading, stress ratio, frequency, environment, geometry, cycles, and hold time as conditions.",
        "A scalar remains one scalar observation; never manufacture curve points.",
        "For a curve point set data_kind=series_point, curve_role=curve_point, series_id, and series_origin=source_table, supplementary_data, or figure_digitized.",
        "Ordinary figure metadata is not numerical evidence. Figure digitizations remain outside canonical admission.",
    ]
