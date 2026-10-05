"""Narrow structural normalization for recognizable Mechanical provider JSON.

This module changes representation only.  It never creates scientific values,
conditions, ownership, or evidence, and it deliberately leaves unsupported
provider fields in the separately retained raw response.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class MechanicalProviderNormalizationError(ValueError):
    """The provider payload is not one of the safely recognized alternate shapes."""


_MISSING_TEXT = {
    "", "-", "--", "—", "–", "n/a", "na", "n.a.", "not available",
    "not measured", "not reported", "missing",
}
_EVIDENCE_FIELDS = {
    "source_id", "page", "section", "source_type", "original_source_type",
    "verbatim_match", "text_snippet", "table_id", "figure_id", "locator",
    "confidence",
}
_MEASUREMENT_FIELDS = {
    "property", "raw_value", "value", "unit", "normalized_value",
    "normalized_unit", "uncertainty", "uncertainty_unit", "qualifier", "method",
}


def is_missing_source_value(value: Any) -> bool:
    """Return true only for explicit missing-value markers, never ordinary zeroes."""
    return isinstance(value, str) and value.strip().casefold() in _MISSING_TEXT


@dataclass
class _Audit:
    mapped_fields: set[str] = field(default_factory=set)
    normalized_record_ids: list[str] = field(default_factory=list)
    omitted_missing_measurements: int = 0
    omitted_missing_conditions: int = 0
    raw_only_fields: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalization_source": "provider_structure_normalization",
            "mapped_fields": sorted(self.mapped_fields),
            "normalized_record_ids": self.normalized_record_ids,
            "omitted_missing_measurements": self.omitted_missing_measurements,
            "omitted_missing_conditions": self.omitted_missing_conditions,
            "raw_only_fields": sorted(self.raw_only_fields),
            "scientific_values_created": 0,
            "evidence_created": 0,
        }


def _as_list(value: Any, field_name: str) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise MechanicalProviderNormalizationError(f"{field_name} must be a list")


def _evidence_from_source(source: Any) -> list[dict]:
    if source is None:
        return []
    if not isinstance(source, dict):
        raise MechanicalProviderNormalizationError("measurement source must be an object")
    evidence = {key: deepcopy(value) for key, value in source.items() if key in _EVIDENCE_FIELDS}
    return [evidence] if evidence else []


def _normalize_conditions(value: Any, audit: _Audit) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        result = deepcopy(value)
        result["normalization_source"] = "provider_structure_normalization"
        return result
    if not isinstance(value, list):
        raise MechanicalProviderNormalizationError("measurement conditions must be an object or named list")
    result: dict[str, Any] = {"normalization_source": "provider_structure_normalization"}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise MechanicalProviderNormalizationError("alternate conditions require named objects")
        name = item["name"].strip()
        raw = item.get("raw_value")
        direct = item.get("value")
        if is_missing_source_value(raw) or is_missing_source_value(direct):
            audit.omitted_missing_conditions += 1
            continue
        if direct is not None:
            result[name] = deepcopy(direct)
        elif raw is not None:
            result[name] = deepcopy(raw)
        if raw is not None:
            result[f"{name}_raw_value"] = deepcopy(raw)
        if item.get("unit") is not None:
            result[f"{name}_unit"] = deepcopy(item["unit"])
    audit.mapped_fields.add("conditions:name_list->conditions:object")
    return result


def _normalize_measurement(item: Any, audit: _Audit) -> dict | None:
    if not isinstance(item, dict) or not isinstance(item.get("property"), str):
        raise MechanicalProviderNormalizationError("measurements require a property")
    if is_missing_source_value(item.get("raw_value")) or is_missing_source_value(item.get("value")):
        audit.omitted_missing_measurements += 1
        return None
    result = {key: deepcopy(value) for key, value in item.items() if key in _MEASUREMENT_FIELDS}
    result["conditions"] = _normalize_conditions(item.get("conditions"), audit)
    evidence = item.get("evidence")
    if evidence is None and "source" in item:
        evidence = _evidence_from_source(item.get("source"))
        audit.mapped_fields.add("measurement.source->measurement.evidence")
    result["evidence"] = deepcopy(evidence) if evidence is not None else []
    unknown = set(item) - _MEASUREMENT_FIELDS - {"conditions", "evidence", "source"}
    audit.raw_only_fields.update(f"measurement.{key}" for key in unknown)
    return result


def _normalize_material(item: Any, audit: _Audit) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("local_id"), str):
        raise MechanicalProviderNormalizationError("materials require local_id")
    allowed = {
        "local_id", "name", "formula", "elements", "phase", "morphology",
        "defects", "dopants", "tags", "ownership", "evidence",
    }
    result = {key: deepcopy(value) for key, value in item.items() if key in allowed}
    if "formula" not in result and item.get("chemical_formula") is not None:
        result["formula"] = deepcopy(item["chemical_formula"])
        audit.mapped_fields.add("material.chemical_formula->material.formula")
    composition = item.get("composition")
    if isinstance(composition, dict):
        result["composition"] = deepcopy(composition)
    elif composition is not None:
        audit.raw_only_fields.add("material.composition_noncanonical")
    audit.raw_only_fields.update(
        f"material.{key}" for key in set(item) - allowed - {"chemical_formula", "composition"}
    )
    audit.normalized_record_ids.append(item["local_id"])
    return result


def _normalize_process(item: Any, audit: _Audit) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("local_id"), str) or not isinstance(item.get("name"), str):
        raise MechanicalProviderNormalizationError("processes require local_id and name")
    allowed = {"local_id", "name", "family", "atmosphere", "equipment", "evidence", "ownership"}
    result = {key: deepcopy(value) for key, value in item.items() if key in allowed}
    refs = item.get("material_refs", item.get("input_materials", []))
    result["material_refs"] = _as_list(refs, "process material references")
    parameters = item.get("parameters", item.get("conditions", []))
    normalized_parameters = []
    for parameter in _as_list(parameters, "process parameters"):
        if not isinstance(parameter, dict):
            raise MechanicalProviderNormalizationError("process parameters must be objects")
        candidate = deepcopy(parameter)
        if "property" not in candidate and isinstance(candidate.get("parameter"), str):
            candidate["property"] = candidate.pop("parameter")
            audit.mapped_fields.add("process.condition.parameter->process.parameter.property")
        normalized = _normalize_measurement(candidate, audit)
        if normalized is not None:
            normalized_parameters.append(normalized)
    result["parameters"] = normalized_parameters
    audit.raw_only_fields.update(
        f"process.{key}" for key in set(item) - allowed - {
            "material_refs", "input_materials", "parameters", "conditions",
        }
    )
    audit.normalized_record_ids.append(item["local_id"])
    return result


def _normalize_experiment(item: Any, audit: _Audit) -> dict:
    if not isinstance(item, dict) or not isinstance(item.get("local_id"), str):
        raise MechanicalProviderNormalizationError("experiments require local_id")
    experiment_type = item.get("experiment_type", item.get("name"))
    if not isinstance(experiment_type, str) or not experiment_type.strip():
        raise MechanicalProviderNormalizationError("experiments require experiment_type or name")
    result = {
        "local_id": item["local_id"],
        "experiment_type": experiment_type,
        "ownership": item.get("ownership", "unknown"),
    }
    if "name" in item and "experiment_type" not in item:
        audit.mapped_fields.add("experiment.name->experiment.experiment_type")
    if "material_refs" in item:
        result["material_refs"] = _as_list(item["material_refs"], "experiment material_refs")
    elif item.get("material_id") is not None:
        result["material_refs"] = [item["material_id"]]
        audit.mapped_fields.add("experiment.material_id->experiment.material_refs")
    else:
        result["material_refs"] = []
    if item.get("target") is not None:
        result["target"] = deepcopy(item["target"])
    if item.get("description") is not None and item.get("protocol") is None:
        result["protocol"] = deepcopy(item["description"])
        audit.mapped_fields.add("experiment.description->experiment.protocol")
    elif item.get("protocol") is not None:
        result["protocol"] = deepcopy(item["protocol"])
    result["conditions"] = [
        normalized for condition in _as_list(item.get("conditions", []), "experiment conditions")
        if (normalized := _normalize_measurement(condition, audit)) is not None
    ]
    outputs = item.get("outputs", item.get("measurements", []))
    result["outputs"] = [
        normalized for measurement in _as_list(outputs, "experiment measurements")
        if (normalized := _normalize_measurement(measurement, audit)) is not None
    ]
    if "measurements" in item and "outputs" not in item:
        audit.mapped_fields.add("experiment.measurements->experiment.outputs")
    result["evidence"] = deepcopy(item.get("evidence", []))
    audit.raw_only_fields.update(
        f"experiment.{key}" for key in set(item) - {
            "local_id", "experiment_type", "name", "ownership", "material_refs",
            "material_id", "target", "protocol", "description", "conditions",
            "outputs", "measurements", "evidence",
        }
    )
    audit.normalized_record_ids.append(item["local_id"])
    return result


def normalize_mechanical_provider_payload(payload: dict) -> tuple[dict, dict]:
    """Normalize only the explicit alternate Mechanical representation."""
    if not isinstance(payload, dict):
        raise MechanicalProviderNormalizationError("Mechanical payload must be an object")
    recognizable = any(
        isinstance(item, dict) and ({"measurements", "material_id", "name"} & set(item))
        for item in payload.get("experiments", []) if isinstance(payload.get("experiments"), list)
    ) or any(
        isinstance(item, dict) and ({"input_materials", "conditions"} & set(item))
        for item in payload.get("processes", []) if isinstance(payload.get("processes"), list)
    )
    if not recognizable:
        raise MechanicalProviderNormalizationError("No recognized alternate Mechanical structure")

    audit = _Audit()
    domain_values = payload.get("domain_values", {})
    if domain_values == []:
        domain_values = {}
        audit.mapped_fields.add("empty_domain_values_list->domain_values_object")
    if not isinstance(domain_values, dict):
        raise MechanicalProviderNormalizationError("domain_values is not an object or empty list")
    normalized = {
        "source": deepcopy(payload.get("source", {})),
        "materials": [_normalize_material(item, audit) for item in _as_list(payload.get("materials", []), "materials")],
        "processes": [_normalize_process(item, audit) for item in _as_list(payload.get("processes", []), "processes")],
        "experiments": [_normalize_experiment(item, audit) for item in _as_list(payload.get("experiments", []), "experiments")],
        "calculations": deepcopy(_as_list(payload.get("calculations", []), "calculations")),
        "domain_values": deepcopy(domain_values),
        "extraction_notes": deepcopy(_as_list(payload.get("extraction_notes", []), "extraction_notes")),
    }
    audit_dict = audit.as_dict()
    normalized["domain_values"]["provider_structure_normalization"] = audit_dict
    normalized["extraction_notes"].append(
        "Provider representation was structurally normalized before strict Mechanical validation; raw output retained separately."
    )
    return normalized, audit_dict
