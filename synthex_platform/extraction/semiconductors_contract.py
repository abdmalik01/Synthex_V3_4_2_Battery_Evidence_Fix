"""Conservative scientific admission for semiconductor specimens and results.

The value in a scaled table column remains in the publisher's displayed unit;
normalization is optional and is checked against an explicit conversion table.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from synthex_platform.core.models import Measurement
from .draft_models import DraftDevice


@dataclass(frozen=True)
class SemiconductorDecision:
    admitted: bool
    reason: str


_RESULT_FAMILIES = {
    "band_gap": "energy", "electronic_band_gap": "energy", "optical_band_gap": "energy",
    "work_function": "energy", "electron_affinity": "energy", "ionization_energy": "energy",
    "fermi_level": "energy", "effective_mass": "mass", "calculated_band_gap": "energy",
    "calculated_effective_mass": "mass", "carrier_concentration": "density",
    "activated_carrier_concentration": "density", "electron_concentration": "density",
    "hole_concentration": "density", "dopant_concentration": "density",
    "carrier_mobility": "mobility", "electron_mobility": "mobility",
    "hole_mobility": "mobility", "hall_mobility": "mobility",
    "conductivity": "conductivity", "resistivity": "resistivity",
    "sheet_resistance": "sheet_resistance", "hall_coefficient": "hall_coefficient",
    "threshold_voltage": "voltage", "on_off_ratio": "dimensionless",
    "subthreshold_swing": "subthreshold", "contact_resistance": "contact_resistance",
    "breakdown_voltage": "voltage", "breakdown_field": "field",
    "current_density": "current_density", "absorption_coefficient": "absorption",
    "absorption_edge": "wavelength", "photoluminescence_peak": "peak",
    "emission_wavelength": "wavelength", "refractive_index": "dimensionless",
    "dielectric_constant": "dimensionless", "crystallite_size": "length",
    "defect_formation_energy": "energy", "activation_energy": "energy",
}
_PROCESS_FAMILIES = {
    "film_thickness": "length", "dopant_atomic_fraction": "percent",
    "dopant_concentration": "density", "growth_temperature": "temperature",
    "substrate_temperature": "temperature", "annealing_temperature": "temperature",
    "annealing_time": "time", "tempering_temperature": "temperature",
    "tempering_time": "time",
}
_UNITS = {
    "energy": {"ev"}, "mass": {"me", "m0"},
    "density": {"cm-3", "m-3", "1/cm3", "1/m3", "x1020cm-3"},
    "mobility": {"cm2/v/s", "m2/v/s", "cm2/vs", "m2/vs", "x10-2cm2/v/s", "x10-3cm2/v/s"},
    "conductivity": {"s/cm", "s/m"},
    "resistivity": {"ohmcm", "ohmm", "x10-3ohmcm"},
    "sheet_resistance": {"ohm/sq", "ohm/square"},
    "hall_coefficient": {"cm3/c", "m3/c", "x10-2cm3/c"},
    "voltage": {"v", "mv"}, "dimensionless": {"1", "dimensionless"},
    "subthreshold": {"mv/dec", "v/dec"},
    "contact_resistance": {"ohm", "ohmcm", "ohmmm"},
    "field": {"v/cm", "kv/cm", "megav/cm"},
    "current_density": {"a/cm2", "ma/cm2", "a/m2"},
    "absorption": {"cm-1", "m-1"}, "wavelength": {"nm", "um"},
    "peak": {"ev", "nm", "um"}, "length": {"nm", "um", "mm"},
    "percent": {"%", "at.%"}, "temperature": {"c", "k"},
    "time": {"s", "min", "h"},
}
_SCALED_UNITS = {
    ("density", "x1020cm-3"): ("cm-3", 1e20),
    ("resistivity", "x10-3ohmcm"): ("ohmcm", 1e-3),
    ("hall_coefficient", "x10-2cm3/c"): ("cm3/c", 1e-2),
    ("mobility", "x10-2cm2/v/s"): ("cm2/v/s", 1e-2),
    ("mobility", "x10-3cm2/v/s"): ("cm2/v/s", 1e-3),
}
_MISSING = {"n/a", "na", "-", "--", "not reported", "not measured"}
_NUMBER = re.compile(r"^\s*([+\-−]?\s*(?:\d+(?:\.\d*)?|\.\d+))(?:\s*[×x*]\s*10\s*\^?\s*([+\-−]?\s*\d+))?\s*$")


def _unit_key(unit: str | None) -> str:
    # Preserve the SI-prefix case distinction: MV/cm is mega-, mV/cm is milli-.
    value = (unit or "").replace("MV/cm", "megaV/cm")
    return (
        value.casefold().replace("×", "x").replace("−", "-")
        .replace("²", "2").replace("³", "3").replace("µ", "u").replace("μ", "u")
        .replace("ω", "ohm").replace("Ω", "ohm").replace("Ω", "ohm")
        .replace("·", "").replace("*", "").replace("^", "")
        .replace(" ", "").replace("(", "").replace(")", "")
    )


def _raw_number(raw: str) -> float | None:
    match = _NUMBER.fullmatch(raw)
    if not match:
        return None
    base = float(match[1].replace("−", "-").replace(" ", ""))
    exponent = int(match[2].replace("−", "-").replace(" ", "")) if match[2] else 0
    return base * (10 ** exponent)


def _verbatim_value_evidence(measurement: Measurement) -> bool:
    raw = " ".join((measurement.raw_value or "").split()).casefold()
    return any(
        evidence.verbatim_match is True
        and evidence.page is not None
        and evidence.source_type.value in {"table", "text", "supplementary", "computation"}
        and "caption" not in (evidence.original_source_type or "").casefold()
        and (evidence.table_id or evidence.locator)
        and raw in " ".join((evidence.text_snippet or "").split()).casefold()
        for evidence in measurement.evidence
    )


def semiconductor_admission_decision(
    measurement: Measurement, *, role: str, modality: str = "experimental",
) -> SemiconductorDecision:
    families = _PROCESS_FAMILIES if role == "process_parameter" else _RESULT_FAMILIES if role == "result" else {}
    family = families.get(measurement.property)
    if family is None:
        return SemiconductorDecision(False, "unknown_or_role_mismatched_semiconductor_property")
    if not measurement.raw_value or measurement.raw_value.strip().casefold() in _MISSING:
        return SemiconductorDecision(False, "missing_or_non_numeric_source_value")
    if not _verbatim_value_evidence(measurement):
        return SemiconductorDecision(False, "no_page_verbatim_value_evidence")
    if not isinstance(measurement.value, (int, float)) or isinstance(measurement.value, bool) or not math.isfinite(measurement.value):
        return SemiconductorDecision(False, "finite_numeric_value_required")
    parsed = _raw_number(measurement.raw_value)
    if parsed is None or not math.isclose(parsed, measurement.value, rel_tol=1e-9, abs_tol=1e-12):
        return SemiconductorDecision(False, "raw_numeric_value_mismatch")
    unit = _unit_key(measurement.unit)
    if unit not in _UNITS[family]:
        return SemiconductorDecision(False, f"invalid_{family}_unit")
    if measurement.normalized_value is not None or measurement.normalized_unit is not None:
        conversion = _SCALED_UNITS.get((family, unit))
        if conversion is None:
            return SemiconductorDecision(False, "unverified_unit_conversion")
        target, factor = conversion
        if _unit_key(measurement.normalized_unit) != target or not isinstance(measurement.normalized_value, (int, float)) or not math.isclose(measurement.normalized_value, measurement.value * factor, rel_tol=1e-9, abs_tol=1e-15):
            return SemiconductorDecision(False, "incorrect_scaled_unit_conversion")
    scientific_type = measurement.conditions.get("scientific_type")
    if role == "process_parameter":
        if scientific_type != "reported_process_parameter":
            return SemiconductorDecision(False, "process_scientific_type_required")
    elif modality == "computational":
        if scientific_type != "calculated":
            return SemiconductorDecision(False, "computational_result_must_be_calculated")
    elif modality == "experimental":
        if scientific_type not in {"reported_measurement", "reported_derived_metric"}:
            return SemiconductorDecision(False, "experimental_scientific_type_required")
        if measurement.property in {"calculated_band_gap", "calculated_effective_mass", "defect_formation_energy"}:
            return SemiconductorDecision(False, "calculated_property_in_experiment")
    else:
        return SemiconductorDecision(False, "invalid_semiconductor_modality")
    if role == "result" and not measurement.conditions.get("sample_label"):
        return SemiconductorDecision(False, "missing_specimen_identity")
    if measurement.property == "optical_band_gap" and not measurement.conditions.get("derivation_basis"):
        return SemiconductorDecision(False, "missing_optical_gap_derivation")
    if measurement.property == "hall_mobility" and measurement.method != "Hall_effect":
        return SemiconductorDecision(False, "hall_mobility_method_required")
    if measurement.property == "dopant_concentration" and measurement.conditions.get("carrier_identity"):
        return SemiconductorDecision(False, "dopant_carrier_conflation")
    return SemiconductorDecision(True, "admitted")


def semiconductor_device_decision(device: DraftDevice) -> SemiconductorDecision:
    if device.device_type not in {"semiconductor_thin_film", "semiconductor_wafer", "semiconductor_heterostructure", "semiconductor_device"}:
        return SemiconductorDecision(False, "unrecognized_semiconductor_specimen_type")
    roles = [layer.role for layer in device.layer_stack]
    if device.device_type == "semiconductor_thin_film" and (roles.count("semiconductor_film") != 1 or roles.count("substrate") != 1):
        return SemiconductorDecision(False, "film_and_substrate_layers_required")
    if not device.configuration.get("sample_label"):
        return SemiconductorDecision(False, "sample_label_required")
    if not all(layer.evidence and any(e.verbatim_match is True for e in layer.evidence) for layer in device.layer_stack):
        return SemiconductorDecision(False, "layer_source_evidence_required")
    return SemiconductorDecision(True, "admitted")
