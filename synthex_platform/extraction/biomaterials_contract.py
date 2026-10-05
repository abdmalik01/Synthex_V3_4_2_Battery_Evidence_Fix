"""Biomaterial result admission: specimen, assay, context, unit and value evidence."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from synthex_platform.core.models import Measurement
from .draft_models import DraftDevice


@dataclass(frozen=True)
class BiomaterialsDecision:
    admitted: bool
    reason: str


# These are distinct scientific endpoints, not interchangeable aliases.
RESULT_UNITS = {
    "cell_viability": {"%"}, "cell_proliferation_ratio": {"1", "fold"},
    "cell_adhesion": {"%", "cells/cm2"}, "live_dead_fraction": {"%"},
    "cytotoxicity": {"%"}, "metabolic_activity": {"%", "1", "fold"},
    "hemolysis": {"%"}, "platelet_adhesion": {"cells/cm2", "%"},
    "alp_activity": {"u/l", "u/mg", "nmol/min/mg"},
    "mineralization": {"%", "mg/cm2"}, "apatite_formation": {"%"},
    "inhibition_zone": {"mm"}, "bacterial_viability": {"%"},
    "cfu_reduction": {"%"}, "log_reduction": {"log10"},
    "mass_loss": {"%"}, "degradation_rate": {"%/day", "%/week", "mg/day"},
    "swelling_ratio": {"%"}, "water_uptake": {"%"},
    "volume_porosity": {"%"}, "porosity": {"%"},
    "pore_size": {"um", "mm"}, "pore_diameter": {"um", "mm"},
    "strut_diameter": {"um", "mm"}, "fiber_diameter": {"um", "nm"},
    "deposited_layer_width": {"um", "mm"},
    "contact_angle": {"degree"}, "surface_roughness": {"nm", "um"},
    "compressive_yield_strength": {"mpa", "kpa"},
    "ultimate_compressive_strength": {"mpa", "kpa"},
    "compressive_modulus": {"mpa", "kpa"}, "elastic_modulus": {"mpa", "kpa"},
    "tensile_strength": {"mpa", "kpa"},
    "cold_crystallization_temperature": {"c", "k"},
    "melting_enthalpy": {"j/g"}, "crystallinity": {"%"},
    "viscosity": {"pa.s"},
}
COMPUTATIONAL_UNITS = {
    "interaction_energy": {"kcal/mol"},
    "electrostatic_interaction_energy": {"kcal/mol"},
}
PROCESS_UNITS = {
    "printing_speed": {"mm/s"}, "nozzle_temperature": {"c", "k"},
    "bed_temperature": {"c", "k"}, "nozzle_diameter": {"mm", "um"},
    "layer_height": {"mm", "um"}, "infill_density": {"%"},
    "polymer_concentration": {"%", "%w/v"}, "crosslinker_concentration": {"%", "mg/ml"},
    "extrusion_pressure": {"kpa"},
}
CELL_RESULTS = {"cell_viability", "cell_proliferation_ratio", "cell_adhesion", "live_dead_fraction", "cytotoxicity", "metabolic_activity", "alp_activity", "mineralization"}
MICROBIAL_RESULTS = {"inhibition_zone", "bacterial_viability", "cfu_reduction", "log_reduction"}
TIME_RESULTS = CELL_RESULTS | {"mass_loss", "degradation_rate", "swelling_ratio", "water_uptake", "hemolysis", "platelet_adhesion", "apatite_formation"}
_NUMBER = re.compile(r"^[+\-−]?(?:\d+(?:\.\d*)?|\.\d+)$")


def biomaterials_result_identity(measurement: Measurement) -> tuple:
    """The dimensions that cannot be merged during scoring or analytics."""
    c = measurement.conditions
    return (
        c.get("sample_label"), c.get("specimen_type"), c.get("process"),
        measurement.property, measurement.unit, measurement.method,
        c.get("cell_line"), c.get("organism"), c.get("strain"),
        c.get("assay"), c.get("exposure_time"), c.get("dilution"),
        c.get("medium"), c.get("scientific_type"),
        c.get("shear_rate_per_s"), c.get("temperature_C"), c.get("crosslinking"),
        c.get("co_culture"), c.get("surface_model"), c.get("biomolecule"), c.get("solvent"),
    )


def _has_value_evidence(measurement: Measurement) -> bool:
    raw = (measurement.raw_value or "").strip()
    return any(
        e.page is not None and e.verbatim_match is True
        and e.source_type.value in {"table", "text", "supplementary", "computation"}
        and "caption" not in (e.original_source_type or "").casefold()
        and (e.table_id or e.locator)
        and raw in (e.text_snippet or "")
        for e in measurement.evidence
    )


def biomaterials_admission_decision(
    measurement: Measurement, *, role: str, modality: str = "experimental",
) -> BiomaterialsDecision:
    units = (PROCESS_UNITS if role == "process_parameter" else
             COMPUTATIONAL_UNITS if role == "result" and modality == "computational" else
             RESULT_UNITS if role == "result" and modality == "experimental" else {})
    allowed = units.get(measurement.property)
    if allowed is None:
        return BiomaterialsDecision(False, "unknown_or_role_mismatched_property")
    if not isinstance(measurement.value, (int, float)) or isinstance(measurement.value, bool) or not math.isfinite(measurement.value):
        return BiomaterialsDecision(False, "finite_numeric_value_required")
    raw = (measurement.raw_value or "").strip().replace("−", "-")
    if not _NUMBER.fullmatch(raw) or not math.isclose(float(raw), measurement.value, rel_tol=1e-9, abs_tol=1e-12):
        return BiomaterialsDecision(False, "raw_numeric_value_mismatch")
    if not _has_value_evidence(measurement):
        return BiomaterialsDecision(False, "no_page_verbatim_value_evidence")
    if (measurement.unit or "").strip().casefold().replace("µ", "u").replace("μ", "u") not in allowed:
        return BiomaterialsDecision(False, "invalid_property_unit")
    if measurement.normalized_value is not None or measurement.normalized_unit is not None:
        return BiomaterialsDecision(False, "unverified_normalization")
    context = measurement.conditions
    if role == "process_parameter":
        if context.get("scientific_type") != "reported_process_parameter":
            return BiomaterialsDecision(False, "process_scientific_type_required")
        return BiomaterialsDecision(True, "admitted")
    if not context.get("sample_label"):
        return BiomaterialsDecision(False, "missing_specimen_identity")
    expected = "calculated" if modality == "computational" else "reported_measurement" if modality == "experimental" else None
    if expected is None or context.get("scientific_type") != expected:
        return BiomaterialsDecision(False, "scientific_type_modality_mismatch")
    if modality == "computational" and not (context.get("surface_model") and context.get("biomolecule")):
        return BiomaterialsDecision(False, "incomplete_computational_model_context")
    if modality == "computational" and measurement.property in CELL_RESULTS | MICROBIAL_RESULTS | {"hemolysis"}:
        return BiomaterialsDecision(False, "biological_assay_cannot_be_calculation")
    if measurement.property in CELL_RESULTS and not (context.get("cell_line") and context.get("assay") and context.get("exposure_time")):
        return BiomaterialsDecision(False, "incomplete_cell_assay_context")
    if measurement.property in MICROBIAL_RESULTS and not (context.get("organism") and context.get("strain") and context.get("assay")):
        return BiomaterialsDecision(False, "incomplete_microbial_assay_context")
    if measurement.property in TIME_RESULTS and not context.get("exposure_time"):
        return BiomaterialsDecision(False, "missing_exposure_time")
    if measurement.property in {"mass_loss", "degradation_rate", "swelling_ratio", "water_uptake"} and not context.get("medium"):
        return BiomaterialsDecision(False, "missing_exposure_medium")
    return BiomaterialsDecision(True, "admitted")


def biomaterials_device_decision(device: DraftDevice) -> BiomaterialsDecision:
    if device.device_type not in {"biomaterial_scaffold", "biomaterial_hydrogel", "biomaterial_implant", "biomaterial_membrane", "biomaterial_filament"}:
        return BiomaterialsDecision(False, "unrecognized_biomaterial_specimen_type")
    if not device.configuration.get("sample_label"):
        return BiomaterialsDecision(False, "missing_specimen_label")
    if len(device.layer_stack) != 1 or device.layer_stack[0].role != "bulk_formulation":
        return BiomaterialsDecision(False, "exactly_one_bulk_formulation_required")
    if not device.layer_stack[0].evidence or not any(e.verbatim_match is True for e in device.layer_stack[0].evidence):
        return BiomaterialsDecision(False, "formulation_evidence_required")
    return BiomaterialsDecision(True, "admitted")
