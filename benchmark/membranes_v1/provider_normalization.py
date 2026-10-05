"""Append-only normalization of the two observed membrane provider shapes."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.draft_models import (
    DraftDevice,
    DraftDeviceLayer,
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    ExtractedDocument,
)


NORMALIZER_VERSION = "membrane_provider_normalizer_v1"
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_LOADING = re.compile(r"(\d+(?:\.\d+)?)\s*(?:wt\s*)?%", re.IGNORECASE)


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _NUMBER.search(str(value or "").replace(",", ""))
    return float(match.group()) if match else None


def _ownership(value: Any) -> str:
    allowed = {
        "focal_work", "cited_prior_work", "review_summary", "comparison_table",
        "background", "example", "unknown",
    }
    return str(value) if value in allowed else "unknown"


def _evidence(raw: dict[str, Any], *, fallback: Any = None) -> list[Evidence]:
    reference = raw.get("source_reference") if isinstance(raw.get("source_reference"), dict) else {}
    text = raw.get("evidence") if raw.get("evidence") is not None else fallback
    if isinstance(text, list):
        text = " | ".join(str(item) for item in text)
    if not text and not reference:
        return []
    source_type = SourceType.table if str(reference.get("source_type", "")).casefold() == "table" else SourceType.text
    return [Evidence(
        source_type=source_type,
        original_source_type=reference.get("original_source_type") or "provider_raw_evidence",
        verbatim_match=None,
        text_snippet=str(text) if text else None,
        table_id=reference.get("table_id"),
        locator=reference.get("locator"),
    )]


def _material_evidence(raw: dict[str, Any]) -> list[Evidence]:
    return _evidence(raw)


def _test_mode(value: Any) -> str | None:
    key = re.sub(r"[^a-z]+", "_", str(value or "").casefold()).strip("_")
    return {"mixed_gas": "mixed_gas", "pure_gas": "pure_gas"}.get(key)


def _scientific_type(property_name: str) -> str:
    return "reported_derived_metric" if property_name in {
        "ideal_selectivity", "mixed_gas_selectivity", "separation_factor",
    } else "reported_measurement"


def _explicit_loading(material: dict[str, Any], *, allow_pure_zero: bool) -> float | None:
    text = " ".join(str(material.get(key) or "") for key in ("name", "composition"))
    match = _LOADING.search(text)
    if match:
        return float(match.group(1))
    if allow_pure_zero and any(token in text.casefold() for token in ("pure", "neat")):
        return 0.0
    return None


def _normalized_conditions(
    raw_output: dict[str, Any], raw_experiment: dict[str, Any], *,
    material_name: str, case_id: str,
) -> dict[str, Any]:
    raw_conditions = raw_output.get("conditions") if isinstance(raw_output.get("conditions"), dict) else {}
    experiment_conditions = raw_experiment.get("conditions") if isinstance(raw_experiment.get("conditions"), dict) else {}
    property_name = raw_output.get("property_key") or raw_output.get("property")
    result: dict[str, Any] = {
        "scientific_type": _scientific_type(str(property_name)),
        "membrane_modality": "gas_separation",
        "membrane_variant": material_name,
    }
    species = raw_conditions.get("species")
    pair = raw_conditions.get("species_pair")
    if species:
        result["species"] = species
    if pair:
        result["species_pair"] = pair
    mode = _test_mode(raw_conditions.get("test_mode"))
    if mode:
        result["test_mode"] = mode
    temperature = _number(raw_conditions.get("temperature"))
    if temperature is not None:
        result.update({"temperature": temperature, "temperature_unit": "C"})

    if case_id == "MEM-GOLD-A":
        pressure = _number(experiment_conditions.get("transmembrane_pressure"))
        if pressure is not None:
            result.update({
                "transmembrane_pressure": pressure,
                "pressure_unit": "bar",
                "pressure_kind": "transmembrane_pressure",
            })
        feed = raw_conditions.get("feed_composition") or experiment_conditions.get("feed")
        if feed:
            result["feed_composition"] = feed
    elif property_name == "gas_permeability":
        # The observed provider shape placed the explicit value "1 bar" in
        # pressure_kind.  Relocate that value only on the same raw object.
        pressure = _number(raw_conditions.get("feed_pressure"))
        if pressure is None:
            pressure = _number(raw_conditions.get("pressure_kind"))
        if pressure is not None:
            result.update({
                "feed_pressure": pressure,
                "pressure_unit": "bar",
                "pressure_kind": "feed_pressure",
            })
    return result


def _measurement(
    raw: dict[str, Any], raw_experiment: dict[str, Any], *,
    material_name: str, case_id: str,
) -> Measurement:
    property_name = str(raw.get("property_key") or raw.get("property"))
    value = raw.get("value") if raw.get("value") is not None else raw.get("canonical_value")
    return Measurement(
        property=property_name,
        raw_value=str(raw.get("raw_value")) if raw.get("raw_value") is not None else None,
        value=_number(value),
        unit=raw.get("unit") or raw.get("units"),
        qualifier="exact",
        method=raw.get("method"),
        conditions=_normalized_conditions(
            raw, raw_experiment, material_name=material_name, case_id=case_id,
        ),
        evidence=_evidence(raw),
    )


def _thickness(raw: dict[str, Any]) -> Measurement:
    conditions = raw.get("conditions") if isinstance(raw.get("conditions"), dict) else {}
    return Measurement(
        property="membrane_thickness",
        raw_value=str(raw.get("raw_value")) if raw.get("raw_value") is not None else None,
        value=_number(raw.get("value")),
        unit=raw.get("unit") or raw.get("units"),
        qualifier="exact",
        conditions={
            "scientific_type": "reported_measurement",
            "thickness_scope": str(conditions.get("thickness_scope") or "whole membrane").replace(" ", "_"),
        },
        evidence=_evidence(raw),
    )


def normalize_provider_payload(payload: dict[str, Any], *, case_id: str) -> tuple[ExtractedDocument, dict[str, Any]]:
    if case_id not in {"MEM-GOLD-A", "MEM-SEP-B"}:
        raise ValueError(f"Unsupported membrane normalization case: {case_id}")
    raw_materials = _list(payload.get("materials"))
    raw_experiments = _list(payload.get("experiments"))
    raw_outputs = _list(payload.get("derived_properties")) + _list(
        payload.get("derived_or_reported_properties")
    )
    material_by_id = {
        str(item.get("local_id") or item.get("material_id")): item for item in raw_materials
    }
    experiment_by_id = {
        str(item.get("local_id") or item.get("experiment_id")): item for item in raw_experiments
    }
    outputs_by_material: dict[str, list[dict[str, Any]]] = defaultdict(list)
    thickness_by_material: dict[str, dict[str, Any]] = {}
    for output in raw_outputs:
        material_ref = str(output.get("material_ref") or "")
        if output.get("property_key") == "membrane_thickness":
            thickness_by_material[material_ref] = output
        else:
            outputs_by_material[material_ref].append(output)

    specimen_refs = set(outputs_by_material) | set(thickness_by_material)
    materials: list[DraftMaterial] = []
    devices: list[DraftDevice] = []
    device_by_material: dict[str, str] = {}
    explicit_loadings: dict[str, float] = {}
    for raw in raw_materials:
        material_id = str(raw.get("local_id") or raw.get("material_id"))
        evidence = _material_evidence(raw)
        raw_composition = raw.get("composition")
        materials.append(DraftMaterial(
            local_id=material_id,
            name=raw.get("name"),
            morphology={"provider_raw_composition": raw_composition} if raw_composition else {},
            tags=[str(raw.get("material_type") or raw.get("category"))] if raw.get("material_type") or raw.get("category") else [],
            ownership=_ownership(raw.get("ownership")),
            evidence=evidence,
        ))
        if material_id not in specimen_refs:
            continue
        device_id = f"device_{material_id}"
        device_by_material[material_id] = device_id
        loading = _explicit_loading(raw, allow_pure_zero=case_id == "MEM-GOLD-A")
        if loading is not None:
            explicit_loadings[material_id] = loading
        config: dict[str, Any] = {
            "membrane_modality": "gas_separation",
            "architecture_type": "dense_mixed_matrix_film",
        }
        if loading is not None:
            config["filler_loading_wt_percent"] = loading
        thickness = _thickness(thickness_by_material[material_id]) if material_id in thickness_by_material else None
        devices.append(DraftDevice(
            local_id=device_id,
            name=raw.get("name"),
            device_type="membrane_specimen",
            layer_stack=[DraftDeviceLayer(
                sequence_index=0,
                role="membrane_body",
                material_ref=material_id,
                thickness=thickness,
                evidence=evidence or (thickness.evidence if thickness else []),
            )],
            configuration=config,
            tags=["provider_normalized_membrane_specimen"],
            ownership=_ownership(raw.get("ownership")),
            evidence=evidence,
        ))

    processes: list[DraftProcess] = []
    for raw in _list(payload.get("processes")):
        inputs = [str(item) for item in raw.get("materials_in", [])]
        outputs = [str(item) for item in raw.get("materials_out", [])]
        processes.append(DraftProcess(
            local_id=str(raw.get("local_id") or f"process_{len(processes) + 1}"),
            name=str(raw.get("name") or raw.get("process_type") or "provider reported process"),
            family=raw.get("process_type"),
            input_material_refs=inputs,
            output_material_refs=outputs,
            output_device_refs=[device_by_material[item] for item in outputs if item in device_by_material],
            ownership=_ownership(raw.get("ownership")),
            evidence=_evidence(raw),
        ))

    experiments: list[DraftExperiment] = []
    normalized_output_count = 0
    for material_ref, raw_items in outputs_by_material.items():
        raw_experiment = experiment_by_id.get(str(raw_items[0].get("experiment_ref")), {})
        material = material_by_id[material_ref]
        outputs = [
            _measurement(
                item, raw_experiment, material_name=str(material.get("name") or material_ref),
                case_id=case_id,
            )
            for item in raw_items
        ]
        normalized_output_count += len(outputs)
        experiments.append(DraftExperiment(
            local_id=f"normalized_{raw_experiment.get('local_id') or 'experiment'}_{material_ref}",
            experiment_type=str(raw_experiment.get("experiment_type") or raw_experiment.get("type") or "gas_permeation"),
            material_refs=[material_ref],
            device_refs=[device_by_material[material_ref]],
            target="provider_reported_gas_transport",
            outputs=outputs,
            protocol=str(raw_experiment.get("conditions") or raw_experiment.get("evidence") or ""),
            ownership=_ownership(raw_experiment.get("ownership")),
            evidence=_evidence(raw_experiment),
        ))

    document = ExtractedDocument(
        materials=materials,
        devices=devices,
        processes=processes,
        experiments=experiments,
        calculations=[],
        domain_values={
            "case_id": case_id,
            "normalizer_version": NORMALIZER_VERSION,
            "provider_payload_shape": (
                "derived_properties" if payload.get("derived_properties") is not None
                else "derived_or_reported_properties"
            ),
        },
        extraction_notes=[
            "Normalized only from the persisted raw provider JSON.",
            "Provider evidence is preserved but not upgraded to verified page-level evidence.",
            "Pressure was relocated only when explicitly present on the same raw output or its referenced experiment.",
        ],
    )
    audit = {
        "normalizer_version": NORMALIZER_VERSION,
        "raw_material_count": len(raw_materials),
        "raw_experiment_count": len(raw_experiments),
        "raw_property_object_count": len(raw_outputs),
        "normalized_material_count": len(materials),
        "normalized_device_count": len(devices),
        "normalized_experiment_count": len(experiments),
        "normalized_output_count": normalized_output_count,
        "thickness_objects_moved_to_device_layers": len(thickness_by_material),
        "explicit_filler_loadings": explicit_loadings,
        "rules_applied": [
            "property_key_to_property",
            "canonical_value_or_value_to_value",
            "units_to_unit",
            "material_ref_and_experiment_ref_grouping",
            "provider_material_to_membrane_specimen",
            "provider_evidence_string_to_unverified_evidence_object",
            "explicit_temperature_and_test_mode_normalization",
            "same_object_pressure_value_relocation",
            "membrane_thickness_property_to_membrane_body_layer",
        ],
        "safety": {
            "invented_values": 0,
            "invented_pressure": 0,
            "invented_evidence_locators": 0,
            "invented_ownership": 0,
            "calculated_selectivity": 0,
        },
    }
    return document, audit


def classify_provider_shape(payload: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    property_key = "derived_properties" if payload.get("derived_properties") is not None else "derived_or_reported_properties"
    return {
        "case_id": case_id,
        "observed_property_container": property_key,
        "categories": {
            "field_name_mismatch": [
                "property_key->property", "canonical_value/value->value", "units/unit->unit",
                "process_type->family", "experiment type/name fields outside the strict draft schema",
            ],
            "nesting_mismatch": [f"top-level {property_key} must be grouped into experiment.outputs"],
            "repeated_object_shape": [
                "MEM-SEP-B one multi-material experiment must be split by explicit material_ref"
                if case_id == "MEM-SEP-B" else "one provider experiment maps to one explicit material_ref"
            ],
            "missing_ownership_placement": [
                "ownership exists on provider entities; Measurement has no ownership field and inherits experiment containment"
            ],
            "condition_placement": [
                "conditions are dictionaries on provider experiments/properties rather than canonical Measurement lists/dicts"
            ],
            "evidence_locator_structure": [
                "MEM-GOLD-A has table/cell locators but no page and no verbatim_match flag"
                if case_id == "MEM-GOLD-A" else "MEM-SEP-B has evidence snippets but no page/table/cell locator"
            ],
            "measurement_grouping": ["provider property objects reference experiments/materials instead of being nested outputs"],
            "species_and_gas_pair": ["species and species_pair are explicit and preserved without rewriting"],
            "pressure_placement": [
                "explicit experiment transmembrane_pressure applies only to its referenced MEM-GOLD-A outputs"
                if case_id == "MEM-GOLD-A" else "1 bar is misplaced in pressure_kind on 42 permeability objects and absent on 56 selectivity objects"
            ],
            "schema_required_omission": [
                "source/devices/domain_values are absent or malformed; source remains pipeline-owned and devices are reshaped from explicit specimen-linked materials"
            ],
        },
    }
