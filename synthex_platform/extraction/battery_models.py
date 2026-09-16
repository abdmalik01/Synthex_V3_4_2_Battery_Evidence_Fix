from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


QUALIFIERS = {"exact", "approx", "lower_bound", "upper_bound", "range", "unknown"}

ResultOwnership = Literal[
    "focal_work",
    "cited_prior_work",
    "review_summary",
    "comparison_table",
    "background",
    "unknown",
]

EVIDENCE_CONFIDENCE_LABELS = {
    "very low": 0.1,
    "low": 0.25,
    "medium": 0.5,
    "moderate": 0.5,
    "high": 0.9,
    "very high": 0.95,
}


class StrictBatteryModel(BaseModel):
    """Reject unrecognized scientific fields after model-specific alias coercion."""

    model_config = ConfigDict(extra="forbid")


def _parse_quantity_string(raw: str) -> dict[str, Any]:
    """Coerce compact scientific strings such as '1.5A', '24 °C', '<0.1 Hz'."""
    text = raw.strip()
    qualifier = "exact"
    probe = text
    if probe.startswith(("~", "≈", "about ", "approximately ")):
        qualifier = "approx"
        probe = re.sub(r"^(?:~|≈|about\s+|approximately\s+)", "", probe, flags=re.I)
    elif probe.startswith((">=", "≥", ">")):
        qualifier = "lower_bound"
        probe = re.sub(r"^(?:>=|≥|>)\s*", "", probe)
    elif probe.startswith(("<=", "≤", "<")):
        qualifier = "upper_bound"
        probe = re.sub(r"^(?:<=|≤|<)\s*", "", probe)
    if re.search(r"\d\s*(?:-|–|—|to)\s*\d", probe, flags=re.I):
        return {"raw_value": text, "value": None, "unit": None, "qualifier": "range"}
    match = re.search(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([^\d\s].*)?$", probe)
    if not match:
        return {"raw_value": text, "value": None, "unit": None, "qualifier": "unknown"}
    try:
        value = float(match.group(1))
    except (TypeError, ValueError):
        value = None
    unit = (match.group(2) or "").strip() or None
    return {"raw_value": text, "value": value, "unit": unit, "qualifier": qualifier}


def _split_voltage_window(raw: str) -> tuple[str | None, str | None]:
    """Best-effort split of strings such as '1.5–4.8 V' without inventing values."""
    text = raw.strip()
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*([-+]?\d+(?:\.\d+)?)\s*([^\d\s].*)?$", text, flags=re.I)
    if not m:
        return None, None
    unit = (m.group(3) or "").strip()
    left = f"{m.group(1)} {unit}".strip()
    right = f"{m.group(2)} {unit}".strip()
    return left, right


def _canonical_property_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    aliases = {
        "specific capacity": "specific_capacity",
        "discharge specific capacity": "specific_capacity",
        "discharge capacity": "specific_capacity",
        "reversible capacity": "specific_capacity",
        "capacity retention": "capacity_retention",
        "coulombic efficiency": "coulombic_efficiency",
        "charge transfer resistance rct": "charge_transfer_resistance",
        "charge transfer resistance": "charge_transfer_resistance",
        "rct": "charge_transfer_resistance",
        "lithium ion diffusion coefficient dli": "diffusion_coefficient",
        "lithium ion diffusion coefficient": "diffusion_coefficient",
        "diffusion coefficient": "diffusion_coefficient",
        "warburg coefficient w": "warburg_coefficient",
        "warburg coefficient": "warburg_coefficient",
        "specific surface area": "specific_surface_area",
        "internal resistance": "internal_resistance",
        "impedance": "impedance",
    }
    if key in aliases:
        return aliases[key]
    if "charge transfer resistance" in key:
        return "charge_transfer_resistance"
    if "diffusion coefficient" in key:
        return "diffusion_coefficient"
    if "warburg coefficient" in key:
        return "warburg_coefficient"
    if "capacity retention" in key:
        return "capacity_retention"
    if "specific capacity" in key or "discharge capacity" in key or "reversible capacity" in key:
        return "specific_capacity"
    if "specific surface area" in key:
        return "specific_surface_area"
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _canonical_condition_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    aliases = {
        "soc": "state_of_charge",
        "state of charge": "state_of_charge",
        "state of charge soc": "state_of_charge",
        "depth of discharge": "depth_of_discharge",
        "dod": "depth_of_discharge",
        "current density": "current_density",
        "areal current density": "current_density",
        "specific current": "specific_current",
        "ambient temperature": "ambient_temperature",
        "internal temperature": "internal_temperature",
    }
    return aliases.get(key) or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class BatteryEvidence(StrictBatteryModel):
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    text_snippet: str | None = None
    source_type: Literal["text", "table", "figure_caption", "figure", "supplementary", "unknown"] = "unknown"
    original_source_type: str | None = None
    table_id: str | None = None
    figure_id: str | None = None
    locator: str | None = None
    verbatim_match: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def coerce_string_evidence(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"text_snippet": data, "source_type": "text", "confidence": None}
        if isinstance(data, dict):
            cleaned = dict(data)
            source_type = cleaned.get("source_type")
            source_type_aliases = {"paragraph": "text"}
            if source_type in source_type_aliases:
                cleaned.setdefault("original_source_type", source_type)
                cleaned["source_type"] = source_type_aliases[source_type]
            confidence = cleaned.get("confidence")
            if isinstance(confidence, str):
                normalized = confidence.strip().lower().replace("_", "-").replace("-", " ")
                if normalized in EVIDENCE_CONFIDENCE_LABELS:
                    cleaned["confidence"] = EVIDENCE_CONFIDENCE_LABELS[normalized]
                else:
                    try:
                        numeric = float(normalized.rstrip("%"))
                        cleaned["confidence"] = numeric / 100 if normalized.endswith("%") else numeric
                    except ValueError:
                        cleaned["confidence"] = None
            return cleaned
        return data


class BatteryQuantity(StrictBatteryModel):
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: Literal["exact", "approx", "lower_bound", "upper_bound", "range", "unknown"] = "unknown"

    @model_validator(mode="before")
    @classmethod
    def coerce_quantity(cls, data: Any) -> Any:
        if data is None:
            return data
        if isinstance(data, (int, float)):
            return {"raw_value": str(data), "value": float(data), "unit": None, "qualifier": "exact"}
        if isinstance(data, str):
            return _parse_quantity_string(data)
        if isinstance(data, dict):
            cleaned = dict(data)
            q = cleaned.get("qualifier")
            if q not in QUALIFIERS:
                cleaned["qualifier"] = "unknown"
            return cleaned
        return data


class BatteryCondition(StrictBatteryModel):
    """A source-backed condition attached to one reported performance point."""

    property: str
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: Literal["exact", "approx", "lower_bound", "upper_bound", "range", "unknown"] = "unknown"
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_condition(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        if cleaned.get("property"):
            cleaned["property"] = _canonical_condition_name(str(cleaned["property"]))
        qualifier = cleaned.get("qualifier")
        if qualifier not in QUALIFIERS:
            raw_value = cleaned.get("raw_value")
            cleaned["qualifier"] = (
                _parse_quantity_string(raw_value)["qualifier"]
                if isinstance(raw_value, str)
                else "unknown"
            )
        evidence = cleaned.get("evidence")
        if evidence is None:
            cleaned["evidence"] = []
        elif not isinstance(evidence, list):
            cleaned["evidence"] = [evidence]
        return cleaned


class BatterySource(StrictBatteryModel):
    title: str | None = None
    doi: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    dataset_source: str | None = None
    pdf_text_parser: Literal["pypdf", "pymupdf"] | None = None


class BatteryProcessStep(StrictBatteryModel):
    step: str
    temperature: BatteryQuantity | None = None
    duration: BatteryQuantity | None = None
    atmosphere: str | None = None
    details: str | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_step_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cleaned = dict(data)
            if cleaned.get("step") is not None and not isinstance(cleaned.get("step"), str):
                cleaned["step"] = str(cleaned["step"])
            ev = cleaned.get("evidence")
            if ev is None:
                cleaned["evidence"] = []
            elif not isinstance(ev, list):
                cleaned["evidence"] = [ev]
            return cleaned
        return data


class BatterySynthesis(StrictBatteryModel):
    method: str | None = None
    precursors: list[str] = Field(default_factory=list)
    solvents: list[str] = Field(default_factory=list)
    chelating_agents: list[str] = Field(default_factory=list)
    precursor_ratio_raw: str | None = None
    steps: list[BatteryProcessStep] = Field(default_factory=list)
    calcination_temperatures: list[BatteryQuantity] = Field(default_factory=list)
    atmosphere: str | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_calcination_temperatures(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        temps = cleaned.get("calcination_temperatures")
        if isinstance(temps, list):
            cleaned["calcination_temperatures"] = [
                {"raw_value": f"{x} °C", "value": float(x), "unit": "°C", "qualifier": "exact"}
                if isinstance(x, (int, float)) else x
                for x in temps
            ]
        return cleaned


class BatteryMaterial(StrictBatteryModel):
    material_id: str
    name: str | None = None
    formula: str | None = None
    role: Literal[
        "cathode", "anode", "active_material", "electrolyte",
        "separator", "additive", "other", "unknown",
    ] = "unknown"
    ownership: ResultOwnership = "unknown"
    composition_raw: str | None = None
    morphology: str | None = None
    phase: str | None = None
    synthesis: BatterySynthesis | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)


class ElectrodeFabrication(StrictBatteryModel):
    active_material: str | None = None
    active_material_fraction: BatteryQuantity | None = None
    conductive_additive: str | None = None
    conductive_fraction: BatteryQuantity | None = None
    binder: str | None = None
    binder_fraction: BatteryQuantity | None = None
    solvent: str | None = None
    current_collector: str | None = None
    coating_method: str | None = None
    mass_loading: BatteryQuantity | None = None
    drying_steps: list[BatteryProcessStep] = Field(default_factory=list)
    pressing_pressure: BatteryQuantity | None = None
    disk_diameter: BatteryQuantity | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        cleaned.setdefault("mass_loading", cleaned.pop("loading", None))

        pressing = cleaned.pop("pressing", None)
        if pressing is not None and cleaned.get("pressing_pressure") is None:
            if isinstance(pressing, str):
                m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(MPa|kPa|Pa|GPa)\b", pressing, flags=re.I)
                cleaned["pressing_pressure"] = {
                    "raw_value": pressing, "value": float(m.group(1)), "unit": m.group(2), "qualifier": "exact"
                } if m else pressing
            else:
                cleaned["pressing_pressure"] = pressing

        dimensions = cleaned.pop("dimensions", None)
        if dimensions is not None and cleaned.get("disk_diameter") is None:
            if isinstance(dimensions, str):
                m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(mm|cm|µm|um)\b", dimensions, flags=re.I)
                cleaned["disk_diameter"] = {
                    "raw_value": dimensions, "value": float(m.group(1)), "unit": m.group(2), "qualifier": "exact"
                } if m else dimensions
            else:
                cleaned["disk_diameter"] = dimensions

        for name_key, frac_key in (("conductive_additive", "conductive_fraction"), ("binder", "binder_fraction")):
            raw = cleaned.get(name_key)
            if isinstance(raw, str) and cleaned.get(frac_key) is None:
                m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)\s*(wt%|mass%|%)\s+(.+)$", raw, flags=re.I)
                if m:
                    cleaned[frac_key] = {
                        "raw_value": f"{m.group(1)} {m.group(2)}", "value": float(m.group(1)),
                        "unit": m.group(2), "qualifier": "exact"
                    }
                    cleaned[name_key] = m.group(3).strip()

        drying = cleaned.pop("drying", None)
        if drying and not cleaned.get("drying_steps"):
            raw = str(drying)
            matches = list(re.finditer(
                r"([-+]?\d+(?:\.\d+)?)\s*°?C\s*(?:for)?\s*([-+]?\d+(?:\.\d+)?)\s*h",
                raw, flags=re.I
            ))
            if matches:
                cleaned["drying_steps"] = [
                    {
                        "step": f"drying_{i}",
                        "temperature": f"{m.group(1)} °C",
                        "duration": f"{m.group(2)} h",
                        "atmosphere": "vacuum" if "vacuum" in raw.lower() else None,
                        "details": raw,
                        "evidence": raw,
                    }
                    for i, m in enumerate(matches, start=1)
                ]
            else:
                cleaned["drying_steps"] = [{"step": "drying", "details": raw, "evidence": raw}]
        elif isinstance(cleaned.get("drying_steps"), list):
            normalized_steps = []
            for index, step in enumerate(cleaned["drying_steps"], start=1):
                if isinstance(step, dict):
                    step = dict(step)
                    if not step.get("step"):
                        step = {"step": f"drying_{index}", **step}
                    for misplaced_field in ("pressing_pressure", "disk_diameter"):
                        if misplaced_field not in step:
                            continue
                        nested_value = step[misplaced_field]
                        parent_value = cleaned.get(misplaced_field)
                        if parent_value is None:
                            cleaned[misplaced_field] = nested_value
                            step.pop(misplaced_field)
                        else:
                            parent_quantity = BatteryQuantity.model_validate(parent_value)
                            nested_quantity = BatteryQuantity.model_validate(nested_value)
                            if parent_quantity.model_dump() == nested_quantity.model_dump():
                                step.pop(misplaced_field)
                normalized_steps.append(step)
            cleaned["drying_steps"] = normalized_steps
        return cleaned


class CellAssembly(StrictBatteryModel):
    cell_format: str | None = None
    counter_electrode: str | None = None
    reference_electrode: str | None = None
    separator: str | None = None
    electrolyte: str | None = None
    electrolyte_volume: BatteryQuantity | None = None
    atmosphere: str | None = None
    glovebox_o2: BatteryQuantity | None = None
    glovebox_h2o: BatteryQuantity | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        cleaned.setdefault("cell_format", cleaned.pop("format", None))
        cleaned.setdefault("atmosphere", cleaned.pop("glovebox_atmosphere", None))
        cleaned.setdefault("glovebox_o2", cleaned.pop("o2_limit", None))
        cleaned.setdefault("glovebox_h2o", cleaned.pop("h2o_limit", None))
        return cleaned


class ChargeProtocol(StrictBatteryModel):
    mode: str | None = None
    constant_current: BatteryQuantity | None = None
    voltage_limit: BatteryQuantity | None = None
    cutoff_current: BatteryQuantity | None = None
    additional_steps: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_text_protocol(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"additional_steps": [data]}
        return data


class DischargeProtocol(StrictBatteryModel):
    mode: str | None = None
    current: BatteryQuantity | None = None
    cutoff_voltage: BatteryQuantity | None = None
    cutoff_voltages: list[BatteryQuantity] = Field(default_factory=list)
    additional_steps: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_text_protocol(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"additional_steps": [data]}
        return data


class ImpedanceProtocol(StrictBatteryModel):
    method: str | None = None
    frequency_min: BatteryQuantity | None = None
    frequency_max: BatteryQuantity | None = None
    amplitude: BatteryQuantity | None = None
    bias: BatteryQuantity | None = None

    @model_validator(mode="before")
    @classmethod
    def coerce_text_protocol(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"method": data}
        return data


class ElectrochemicalTesting(StrictBatteryModel):
    cv_scan_rate: BatteryQuantity | None = None
    voltage_min: BatteryQuantity | None = None
    voltage_max: BatteryQuantity | None = None
    voltage_window: str | None = None
    c_rate_definition: str | None = None
    rate_capability_range: str | None = None
    long_term_cycles: int | None = None
    long_term_c_rate: str | None = None
    temperature: BatteryQuantity | None = None
    equipment: list[str] = Field(default_factory=list)
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        c_rate_definition = cleaned.get("c_rate_definition")
        if isinstance(c_rate_definition, dict):
            raw_value = c_rate_definition.get("raw_value")
            if raw_value is not None:
                cleaned["c_rate_definition"] = str(raw_value)
            elif c_rate_definition.get("value") is not None:
                value = c_rate_definition["value"]
                unit = c_rate_definition.get("unit")
                cleaned["c_rate_definition"] = f"{value} {unit}".strip() if unit else str(value)
            else:
                cleaned["c_rate_definition"] = None
        if cleaned.get("cycle_count") is not None and cleaned.get("long_term_cycles") is None:
            cleaned["long_term_cycles"] = cleaned.pop("cycle_count")
        eq = cleaned.get("equipment")
        if isinstance(eq, str):
            cleaned["equipment"] = [x.strip() for x in re.split(r";|,(?=\s*[A-Z0-9])", eq) if x.strip()]
        window = cleaned.get("voltage_window")
        if isinstance(window, str):
            lo, hi = _split_voltage_window(window)
            if lo and cleaned.get("voltage_min") is None:
                cleaned["voltage_min"] = lo
            if hi and cleaned.get("voltage_max") is None:
                cleaned["voltage_max"] = hi
        return cleaned


class SharedBatteryProtocol(StrictBatteryModel):
    protocol_id: str
    name: str | None = None
    ownership: ResultOwnership = "unknown"
    charge_protocol: ChargeProtocol | None = None
    discharge_protocol: DischargeProtocol | None = None
    impedance_protocol: ImpedanceProtocol | None = None
    electrochemical_testing: ElectrochemicalTesting | None = None
    electrode_fabrication: ElectrodeFabrication | None = None
    cell_assembly: CellAssembly | None = None
    evidence: list[BatteryEvidence] = Field(default_factory=list)


class BatteryDerivation(StrictBatteryModel):
    """Explicit provenance for a value calculated by Synthex, not reported verbatim."""

    reported_property: str
    reported_raw_value: str
    reported_value: float | None = None
    transformation: str


class BatteryPerformancePoint(StrictBatteryModel):
    property: str
    raw_value: str | None = None
    value: float | None = None
    unit: str | None = None
    qualifier: Literal["exact", "approx", "lower_bound", "upper_bound", "range", "unknown"] = "unknown"
    cycle: int | None = None
    c_rate: str | None = None
    voltage_window: str | None = None
    temperature: BatteryQuantity | None = None
    additional_conditions: list[BatteryCondition] = Field(default_factory=list)
    method: str | None = None
    derivation: BatteryDerivation | None = None
    ownership: ResultOwnership = "unknown"
    evidence: list[BatteryEvidence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_property(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cleaned = dict(data)
            if cleaned.get("property"):
                cleaned["property"] = _canonical_property_name(str(cleaned["property"]))
            qualifier = cleaned.get("qualifier")
            if qualifier not in QUALIFIERS:
                raw_value = cleaned.get("raw_value")
                cleaned["qualifier"] = (
                    _parse_quantity_string(raw_value)["qualifier"]
                    if isinstance(raw_value, str)
                    else "unknown"
                )
            evidence = cleaned.get("evidence")
            if evidence is None:
                cleaned["evidence"] = []
            elif not isinstance(evidence, list):
                cleaned["evidence"] = [evidence]
            additional = cleaned.get("additional_conditions")
            if additional is None:
                cleaned["additional_conditions"] = []
            elif not isinstance(additional, list):
                cleaned["additional_conditions"] = [additional]
            return cleaned
        return data


class BatteryConflictValue(StrictBatteryModel):
    value: str
    evidence: list[BatteryEvidence] = Field(default_factory=list)


class BatteryConditionConflict(StrictBatteryModel):
    field: str
    status: Literal["conflicted"] = "conflicted"
    reported_values: list[BatteryConflictValue] = Field(min_length=2)
    resolved_value: str | None = None

    @model_validator(mode="before")
    @classmethod
    def canonicalize_known_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        field = str(cleaned.get("field") or "").strip().lower().replace("-", "_")
        if field in {"c_rate", "long_term_c_rate", "electrochemical_testing.long_term_c_rate"}:
            cleaned["field"] = "c_rate"
        return cleaned


class BatteryGroup(StrictBatteryModel):
    group_id: str
    ownership: ResultOwnership = "unknown"
    battery_ids: list[str] = Field(default_factory=list)
    material_ref: str | None = None
    variant_label: str | None = None
    chemistry: str | None = None
    cathode: str | None = None
    anode: str | None = None
    electrolyte: str | None = None
    cell_format: str | None = None
    temperature: BatteryQuantity | None = None
    calcination_temperature: BatteryQuantity | None = None
    protocol_refs: list[str] = Field(default_factory=list)
    condition_conflicts: list[BatteryConditionConflict] = Field(default_factory=list)
    charge_protocol: ChargeProtocol | None = None
    discharge_protocol: DischargeProtocol | None = None
    impedance_protocol: ImpedanceProtocol | None = None
    electrochemical_testing: ElectrochemicalTesting | None = None
    electrode_fabrication: ElectrodeFabrication | None = None
    cell_assembly: CellAssembly | None = None
    measured_variables: list[str] = Field(default_factory=list)
    performance_points: list[BatteryPerformancePoint] = Field(default_factory=list)
    qualitative_findings: list[str] = Field(default_factory=list)
    evidence: list[BatteryEvidence] = Field(default_factory=list)


class BatteryDocument(StrictBatteryModel):
    _source_text: str | None = PrivateAttr(default=None)
    _pdf_parser: str | None = PrivateAttr(default=None)

    source: BatterySource = Field(default_factory=BatterySource)
    paper_types: list[str] = Field(default_factory=list)
    materials: list[BatteryMaterial] = Field(default_factory=list)
    shared_protocols: list[SharedBatteryProtocol] = Field(default_factory=list)
    battery_groups: list[BatteryGroup] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
