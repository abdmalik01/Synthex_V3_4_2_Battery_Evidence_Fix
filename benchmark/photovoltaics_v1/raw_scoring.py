"""Schema-tolerant scientific scoring for frozen PV provider payloads."""

from __future__ import annotations

from typing import Any


_METRICS = (
    "open_circuit_voltage",
    "short_circuit_current",
    "short_circuit_current_density",
    "fill_factor",
    "power_conversion_efficiency",
)
_STACK = (
    ("substrate", ("glass",)),
    ("transparent_electrode", ("fto", "fluorine-doped tin oxide", "fluorine doped tin oxide")),
    ("etl", ("tio2", "titanium dioxide")),
    ("absorber", ("ch3nh3pbi3", "perovskite")),
    ("htl", ("spiro",)),
    ("electrode", ("au", "gold")),
)


def _objects(payload: dict, key: str) -> list[dict]:
    value = payload.get(key, [])
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return "" if value is None else str(value)


def _variant(value: Any) -> str | None:
    text = _text(value).casefold().replace("-", " ")
    if "bare" in text or "before cmp" in text:
        return "bare"
    for minutes in (5, 10, 15):
        if f"{minutes} min" in text or f"cmp_{minutes}" in text or f"cmp {minutes}" in text:
            return f"cmp_{minutes}_min"
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _measurement_map(experiment: dict) -> dict[str, dict]:
    outputs = experiment.get("outputs", [])
    if isinstance(outputs, dict):
        outputs = [outputs]
    return {
        item.get("property"): item
        for item in outputs
        if isinstance(item, dict) and isinstance(item.get("property"), str)
    }

def _resolved_layer_text(layer: dict, materials: dict[str, dict]) -> str:
    ref = layer.get("material_ref") or layer.get("material_id")
    material = materials.get(str(ref), {})
    return f"{_text(ref)} {_text(material)}".casefold().replace(" ", "")


def _has_value_evidence(measurement: dict, expected_label: str) -> bool:
    evidence = measurement.get("evidence", [])
    if isinstance(evidence, dict):
        evidence = [evidence]
    raw = str(measurement.get("raw_value") or "").casefold()
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("text_snippet") or "").casefold()
        locator = str(item.get("locator") or "").casefold()
        table = str(item.get("table_id") or "").casefold()
        if (
            item.get("page") == 8
            and ("table 2" in table or "table" in str(item.get("source_type") or "").casefold())
            and raw and raw in snippet
            and (expected_label.casefold() in locator or "row=" in locator)
        ):
            return True
    return False


def score_raw_gold_a(payload: dict, gold: dict) -> dict:
    """Score initial provider JSON without requiring it to satisfy Pydantic schemas."""
    materials = {
        str(item.get("local_id") or item.get("material_id")): item
        for item in _objects(payload, "materials")
    }
    devices = _objects(payload, "devices")
    device_by_variant = {_variant(item): item for item in devices if _variant(item)}
    device_ref_variant = {
        str(item.get("local_id") or item.get("device_id")): variant
        for variant, item in device_by_variant.items()
    }
    experiments = _objects(payload, "experiments")
    experiments_by_variant: dict[str, dict] = {}
    for experiment in experiments:
        refs = experiment.get("device_refs") or experiment.get("device_ids") or []
        if isinstance(refs, str):
            refs = [refs]
        variant = next((device_ref_variant.get(str(ref)) for ref in refs if device_ref_variant.get(str(ref))), None)
        variant = variant or _variant(experiment)
        if variant and len(_measurement_map(experiment)) > len(_measurement_map(experiments_by_variant.get(variant, {}))):
            experiments_by_variant[variant] = experiment

    rows = []
    totals = {
        "device_identity": 0,
        "stack_role_material": 0,
        "metric_value": 0,
        "uncertainty": 0,
        "device_association": 0,
        "measurement_context": 0,
        "value_specific_evidence": 0,
        "focal_ownership": 0,
    }
    for expected in gold["rows"]:
        variant = expected["variant"]
        device = device_by_variant.get(variant)
        experiment = experiments_by_variant.get(variant)
        measurements = _measurement_map(experiment or {})
        identity = device is not None
        totals["device_identity"] += int(identity)
        stack = (device or {}).get("layer_stack") or (device or {}).get("configuration", {}).get("layer_stack") or []
        if isinstance(stack, dict):
            stack = [stack]
        stack = sorted(
            [item for item in stack if isinstance(item, dict)],
            key=lambda item: item.get("sequence_index", 10**6),
        )
        stack_hits = 0
        for index, (role, aliases) in enumerate(_STACK):
            if index >= len(stack):
                continue
            layer = stack[index]
            layer_text = _resolved_layer_text(layer, materials)
            if str(layer.get("role", "")).casefold() == role and any(
                alias.replace(" ", "") in layer_text for alias in aliases
            ):
                stack_hits += 1
        totals["stack_role_material"] += stack_hits

        metric_hits = uncertainty_hits = association_hits = context_hits = evidence_hits = 0
        for property_name in _METRICS:
            measurement = measurements.get(property_name)
            expected_value, expected_uncertainty, _ = expected[property_name]
            if measurement and _number(measurement.get("value")) == float(expected_value):
                metric_hits += 1
            if measurement and _number(measurement.get("uncertainty")) == float(expected_uncertainty):
                uncertainty_hits += 1
            if measurement and experiment is not None:
                association_hits += 1
            conditions = measurement.get("conditions", {}) if measurement else {}
            if measurement and (
                "am 1.5 g" in _text(conditions).casefold()
                and _number(conditions.get("irradiance")) == 100.0
            ):
                context_hits += 1
            if measurement and _has_value_evidence(measurement, expected["label"]):
                evidence_hits += 1
        totals["metric_value"] += metric_hits
        totals["uncertainty"] += uncertainty_hits
        totals["device_association"] += association_hits
        totals["measurement_context"] += context_hits
        totals["value_specific_evidence"] += evidence_hits
        focal = bool(
            device and device.get("ownership") == "focal_work"
            and experiment and experiment.get("ownership") == "focal_work"
        )
        totals["focal_ownership"] += int(focal)
        rows.append({
            "variant": variant,
            "device_found": identity,
            "ordered_stack_layers": stack_hits,
            "metric_values": metric_hits,
            "uncertainties": uncertainty_hits,
            "device_associations": association_hits,
            "contexts": context_hits,
            "evidence": evidence_hits,
            "focal_ownership": focal,
        })

    all_measurements = [
        measurement
        for experiment in experiments
        for measurement in _measurement_map(experiment).values()
    ]
    invented_active_area = any(
        measurement.get("conditions", {}).get("active_area") not in (None, "", "not reported")
        for measurement in all_measurements
    )
    invented_scan_direction = any(
        measurement.get("conditions", {}).get("scan_direction") not in (None, "", "not reported")
        for measurement in all_measurements
    )
    properties = [measurement.get("property") for measurement in all_measurements]
    return {
        "case_id": gold["case_id"],
        "initial_payload_scored": True,
        "rows": rows,
        "scores": {
            "device_identity": f"{totals['device_identity']}/4",
            "ordered_stack_role_material": f"{totals['stack_role_material']}/24",
            "metric_values": f"{totals['metric_value']}/20",
            "reported_uncertainties": f"{totals['uncertainty']}/20",
            "device_association": f"{totals['device_association']}/20",
            "measurement_context": f"{totals['measurement_context']}/20",
            "value_specific_evidence": f"{totals['value_specific_evidence']}/20",
            "focal_ownership": f"{totals['focal_ownership']}/4",
        },
        "safety": {
            "invented_active_area": invented_active_area,
            "invented_scan_direction": invented_scan_direction,
            "device_variants_collapsed": len(device_by_variant) < 4,
            "layer_order_lost": totals["stack_role_material"] < 24,
            "uncertainty_as_separate_metric": any(
                str(item).casefold() in {"uncertainty", "standard_deviation", "std_dev"}
                for item in properties
            ),
            "percentages_collapsed_to_pce": properties.count("power_conversion_efficiency") > 4,
        },
    }
