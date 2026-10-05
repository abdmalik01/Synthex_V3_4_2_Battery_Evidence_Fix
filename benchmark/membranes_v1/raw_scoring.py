"""Scientific scoring for raw Membranes V1 provider payloads."""

from __future__ import annotations

import math
import re
from typing import Any


_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER.search(value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def _expected_points(gold: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if gold["case_id"] == "MEM-GOLD-A":
        for variant in gold["variants"]:
            for species, key in (("CO2", "co2"), ("CH4", "ch4")):
                points.append({
                    "variant": variant["name"], "property": "gas_permeability",
                    "species": species, "species_pair": None,
                    "value": variant[key][0], "unit": "Barrer",
                })
            points.append({
                "variant": variant["name"], "property": "mixed_gas_selectivity",
                "species": None, "species_pair": "CO2/CH4",
                "value": variant["selectivity"][0], "unit": "dimensionless",
            })
        return points
    for variant in gold["variants"]:
        for species, value in zip(gold["species_order"], variant["permeability"], strict=True):
            points.append({
                "variant": variant["name"], "property": "gas_permeability",
                "species": species, "species_pair": None,
                "value": value, "unit": "Barrer",
            })
        for pair, value in zip(gold["pair_order"], variant["ideal_selectivity"], strict=True):
            points.append({
                "variant": variant["name"], "property": "ideal_selectivity",
                "species": None, "species_pair": pair,
                "value": value, "unit": "dimensionless",
            })
    return points


def _device_names(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for device in _items(payload.get("devices")):
        name = str(device.get("name") or "")
        for key in ("local_id", "device_id", "id"):
            if device.get(key):
                result[str(device[key])] = name
    return result


def _material_names(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for material in _items(payload.get("materials")):
        name = str(material.get("name") or "")
        for key in ("local_id", "material_id", "id"):
            if material.get(key):
                result[str(material[key])] = name
    return result


def _outputs(payload: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    experiments = _items(payload.get("experiments"))
    experiment_map = {
        str(experiment.get("local_id") or experiment.get("experiment_id") or experiment.get("id")): experiment
        for experiment in experiments
    }
    for experiment in experiments:
        result.extend((output, experiment) for output in _items(experiment.get("outputs")))
    result.extend((output, {}) for output in _items(payload.get("measurements")))
    derived_rows = _items(payload.get("derived_properties")) + _items(
        payload.get("derived_or_reported_properties")
    )
    for derived in derived_rows:
        source_reference = derived.get("source_reference") if isinstance(derived.get("source_reference"), dict) else {}
        evidence = {
            **source_reference,
            "text_snippet": derived.get("evidence") or source_reference.get("text_snippet"),
        }
        output = {
            **derived,
            "property": derived.get("property") or derived.get("property_key"),
            "value": derived.get("value") if derived.get("value") is not None else derived.get("canonical_value"),
            "unit": derived.get("unit") or derived.get("units"),
            "evidence": [evidence] if evidence else [],
        }
        experiment = experiment_map.get(str(derived.get("experiment_ref")), {})
        result.append((output, experiment))
    return result


def _variant_name(
    output: dict[str, Any], experiment: dict[str, Any], devices: dict[str, str], materials: dict[str, str],
) -> str:
    conditions = output.get("conditions") if isinstance(output.get("conditions"), dict) else {}
    direct = conditions.get("membrane_variant") or output.get("membrane_variant")
    if direct:
        return str(direct)
    material_ref = output.get("material_ref")
    if material_ref and str(material_ref) in materials:
        return materials[str(material_ref)]
    refs: list[Any] = []
    for candidate in (output.get("device_ref"), experiment.get("device_id"), experiment.get("device_ref")):
        if candidate:
            refs.append(candidate)
    refs.extend(experiment.get("device_refs") or [])
    refs.extend(experiment.get("device_ids") or [])
    return next((devices[str(ref)] for ref in refs if str(ref) in devices), "")


def _canonical_variant(value: Any, gold: dict[str, Any]) -> str | None:
    normalized = _normalized(value)
    for variant in gold["variants"]:
        if normalized in {_normalized(variant["id"]), _normalized(variant["name"])}:
            return variant["name"]
    loading_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:wt\s*)?%", str(value or ""), flags=re.IGNORECASE)
    loading = float(loading_match.group(1)) if loading_match else 0.0 if any(
        token in normalized for token in ("pure", "neat")
    ) else None
    expanded = normalized
    if normalized.startswith("mk2ph"):
        expanded += "matrimid"
    if normalized.startswith("psfk2ph"):
        expanded += "polysulfone"
    if normalized.startswith("ppok2ph"):
        expanded += "polyphenyleneoxide"
    for variant in gold["variants"]:
        matrix_aliases = {_normalized(variant["matrix"])}
        if "matrimid" in _normalized(variant["matrix"]):
            matrix_aliases.add("matrimid")
        if _normalized(variant["matrix"]) == "polysulfone":
            matrix_aliases.add("psf")
        if _normalized(variant["matrix"]) == "polyphenyleneoxide":
            matrix_aliases.add("ppo")
        candidate_loading = loading
        if candidate_loading is None and "k2ph" not in expanded and "ctf" not in expanded:
            if any(alias and alias in expanded for alias in matrix_aliases):
                candidate_loading = 0.0
        if candidate_loading is None or not math.isclose(
            float(variant["filler_loading"]), candidate_loading, abs_tol=1e-9,
        ):
            continue
        if any(alias and alias in expanded for alias in matrix_aliases):
            return variant["name"]
    return None


def _observed_points(payload: dict[str, Any], gold: dict[str, Any]) -> list[dict[str, Any]]:
    devices = _device_names(payload)
    materials = _material_names(payload)
    observed = []
    for output, experiment in _outputs(payload):
        experiment_conditions = experiment.get("conditions") if isinstance(experiment.get("conditions"), dict) else {}
        output_conditions = output.get("conditions") if isinstance(output.get("conditions"), dict) else {}
        conditions = {**experiment_conditions, **output_conditions}
        evidence = _items(output.get("evidence"))
        observed.append({
            "variant": _canonical_variant(_variant_name(output, experiment, devices, materials), gold),
            "property": output.get("property") or output.get("canonical_property"),
            "species": conditions.get("species") or output.get("species"),
            "species_pair": conditions.get("species_pair") or output.get("species_pair"),
            "value": _number(output.get("value")) if _number(output.get("value")) is not None else _number(output.get("raw_value")),
            "unit": output.get("unit"),
            "conditions": conditions,
            "evidence": evidence,
            "experiment": experiment,
        })
    return observed


def _identity_matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return (
        observed["variant"] == expected["variant"]
        and observed["property"] == expected["property"]
        and _normalized(observed["species"]) == _normalized(expected["species"])
        and _normalized(observed["species_pair"]) == _normalized(expected["species_pair"])
    )


def _unit_matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return _normalized(expected["unit"]) == _normalized(observed["unit"])


def _value_matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return observed["value"] is not None and math.isclose(
        float(expected["value"]), observed["value"], rel_tol=0, abs_tol=1e-9,
    )


def _condition_components(observed: dict[str, Any], gold: dict[str, Any]) -> dict[str, bool]:
    conditions = observed["conditions"]
    expected = gold["conditions"]
    temperature = _number(conditions.get("temperature"))
    temperature_match = temperature is not None and math.isclose(
        temperature, expected["temperature"], abs_tol=1e-9,
    )
    mode_match = _normalized(conditions.get("test_mode")) == _normalized(expected["test_mode"])
    pressure_key = expected["pressure_kind"]
    pressure = _number(conditions.get(pressure_key))
    pressure_match = pressure is not None and math.isclose(
        pressure, expected[pressure_key], abs_tol=1e-9,
    )
    pressure_any = pressure_match
    if not pressure_any:
        misplaced = _number(conditions.get("pressure_kind"))
        pressure_any = misplaced is not None and math.isclose(
            misplaced, expected[pressure_key], abs_tol=1e-9,
        )
    feed_match = True
    if gold["case_id"] == "MEM-GOLD-A":
        feed = _normalized(conditions.get("feed_composition") or conditions.get("feed"))
        expected_feed = _normalized(expected["feed_composition"])
        pair = _normalized(observed.get("species_pair"))
        feed_match = feed == expected_feed or (
            "11" in feed and ("co2ch4" in feed or pair == "co2ch4")
        )
    return {
        "temperature": temperature_match,
        "test_mode": mode_match,
        "pressure_strict": pressure_match,
        "pressure_value_present": pressure_any,
        "feed": feed_match,
        "complete": temperature_match and mode_match and pressure_match and feed_match,
    }


def _condition_matches(observed: dict[str, Any], gold: dict[str, Any]) -> bool:
    return _condition_components(observed, gold)["complete"]


def _filler_associations(payload: dict[str, Any], gold: dict[str, Any]) -> set[tuple[str, float]]:
    devices = _device_names(payload)
    result: set[tuple[str, float]] = set()
    for device in _items(payload.get("devices")):
        variant = _canonical_variant(device.get("name"), gold)
        config = device.get("configuration") if isinstance(device.get("configuration"), dict) else {}
        loading = _number(config.get("filler_loading_wt_percent"))
        if variant and loading is not None:
            result.add((variant, loading))
    for process in _items(payload.get("processes")):
        refs = process.get("output_device_refs") or process.get("device_refs") or []
        variant = next((_canonical_variant(devices.get(str(ref)), gold) for ref in refs if devices.get(str(ref))), None)
        for parameter in _items(process.get("parameters")):
            if parameter.get("property") == "filler_loading" and variant:
                loading = _number(parameter.get("value"))
                if loading is not None:
                    result.add((variant, loading))
    for material in _items(payload.get("materials")):
        text = " ".join(str(material.get(key) or "") for key in ("name", "composition"))
        variant = _canonical_variant(text, gold)
        if not variant:
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:wt\s*)?%", text, flags=re.IGNORECASE)
        loading = float(match.group(1)) if match else 0.0 if any(
            token in _normalized(text) for token in ("pure", "neat")
        ) else None
        if loading is None and "k2ph" not in _normalized(text) and "ctf" not in _normalized(text):
            loading = next(
                (float(item["filler_loading"]) for item in gold["variants"] if item["name"] == variant),
                None,
            )
        if loading is not None:
            result.add((variant, loading))
    return result


def _thickness_associations(payload: dict[str, Any], gold: dict[str, Any]) -> set[tuple[str, float]]:
    result: set[tuple[str, float]] = set()
    materials = _material_names(payload)
    for output, _ in _outputs(payload):
        if (output.get("property") or output.get("property_key")) != "membrane_thickness":
            continue
        variant = _canonical_variant(materials.get(str(output.get("material_ref"))), gold)
        value = _number(output.get("value"))
        if value is None:
            value = _number(output.get("raw_value"))
        if variant and value is not None:
            result.add((variant, value))
    for device in _items(payload.get("devices")):
        variant = _canonical_variant(device.get("name"), gold)
        layers = device.get("layer_stack")
        if not isinstance(layers, list):
            config = device.get("configuration") if isinstance(device.get("configuration"), dict) else {}
            layers = config.get("layer_stack") if isinstance(config.get("layer_stack"), list) else []
        for layer in _items(layers):
            thickness = layer.get("thickness")
            if isinstance(thickness, dict):
                value = _number(thickness.get("value"))
            else:
                value = _number(thickness)
            if variant and value is not None:
                result.add((variant, value))
    return result


def score_raw_case(payload: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    expected = _expected_points(gold)
    observed = _observed_points(payload, gold)
    identity_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    exact_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for point in expected:
        candidates = [item for item in observed if _identity_matches(point, item)]
        if candidates:
            identity_rows.append((point, candidates[0]))
        exact = next((item for item in candidates if _value_matches(point, item) and _unit_matches(point, item)), None)
        if exact:
            exact_rows.append((point, exact))

    variants = {item["variant"] for item in observed if item["variant"]}
    expected_fillers = {(item["name"], float(item["filler_loading"])) for item in gold["variants"]}
    observed_fillers = _filler_associations(payload, gold)
    expected_thickness = {
        (item["name"], float(item["membrane_thickness"][0]))
        for item in gold["variants"] if "membrane_thickness" in item
    }
    observed_thickness = _thickness_associations(payload, gold)
    exact_units = sum(_unit_matches(point, item) for point, item in identity_rows)
    exact_values = sum(_value_matches(point, item) for point, item in identity_rows)
    condition_rows = [_condition_components(item, gold) for _, item in identity_rows]
    condition_matches = sum(item["complete"] for item in condition_rows)
    evidence_count = sum(bool(item["evidence"]) for _, item in identity_rows)
    locator_count = sum(
        bool(item["evidence"]) and any(
            bool(evidence.get("table_id") or evidence.get("locator"))
            and bool(evidence.get("text_snippet"))
            for evidence in item["evidence"]
        )
        for _, item in identity_rows
    )
    page_locator_count = sum(
        bool(item["evidence"]) and any(
            evidence.get("page") is not None
            and bool(evidence.get("table_id") or evidence.get("locator"))
            and bool(evidence.get("text_snippet"))
            for evidence in item["evidence"]
        )
        for _, item in identity_rows
    )
    ownership_objects = [
        item for key in ("materials", "devices", "processes", "experiments")
        for item in _items(payload.get(key)) if item.get("ownership")
    ]
    ownership_objects.extend(
        item
        for key in ("derived_properties", "derived_or_reported_properties")
        for item in _items(payload.get(key))
        if item.get("ownership")
    )
    species = {_normalized(item["species"]) for item in observed if item["species"]}
    pairs = {_normalized(item["species_pair"]) for item in observed if item["species_pair"]}
    expected_species = {_normalized(item["species"]) for item in expected if item["species"]}
    expected_pairs = {_normalized(item["species_pair"]) for item in expected if item["species_pair"]}
    expected_count = len(expected)
    return {
        "case_id": gold["case_id"],
        "raw_output_count": len(observed),
        "membrane_association": {
            "expected_variants": len(gold["variants"]),
            "exact_variants": len(variants),
            "expected_filler_loading_associations": len(expected_fillers),
            "exact_filler_loading_associations": len(expected_fillers & observed_fillers),
            "expected_thickness_associations": len(expected_thickness),
            "exact_thickness_associations": len(expected_thickness & observed_thickness),
        },
        "species_association": {
            "expected_species": len(expected_species),
            "exact_species": len(expected_species & species),
            "expected_gas_pairs": len(expected_pairs),
            "exact_gas_pairs": len(expected_pairs & pairs),
        },
        "condition_association": {
            "identity_points": len(identity_rows),
            "exact_condition_points": condition_matches,
            "temperature_points": sum(item["temperature"] for item in condition_rows),
            "test_mode_points": sum(item["test_mode"] for item in condition_rows),
            "strict_pressure_points": sum(item["pressure_strict"] for item in condition_rows),
            "pressure_value_present_points": sum(item["pressure_value_present"] for item in condition_rows),
            "feed_points": sum(item["feed"] for item in condition_rows),
        },
        "property_accuracy": {
            "expected_points": expected_count,
            "identity_points": len(identity_rows),
            "exact_value_points": exact_values,
            "exact_scientific_points": len(exact_rows),
            "exact_point_recall": len(exact_rows) / expected_count,
        },
        "unit_accuracy": {"identity_points": len(identity_rows), "exact_unit_points": exact_units},
        "evidence": {
            "identity_points": len(identity_rows), "with_evidence": evidence_count,
            "with_table_or_locator": locator_count,
            "with_page_and_table_or_locator": page_locator_count,
        },
        "ownership": {
            "objects_with_ownership": len(ownership_objects),
            "focal_work": sum(item.get("ownership") == "focal_work" for item in ownership_objects),
            "cited_prior_work": sum(item.get("ownership") == "cited_prior_work" for item in ownership_objects),
        },
        "canonical_admission_not_implied": True,
    }
