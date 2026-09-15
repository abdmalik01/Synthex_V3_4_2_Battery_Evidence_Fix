"""Conservative scoring normalization for Catalysis Stage 3 real-paper checkpoints.

This module changes benchmark interpretation only. It does not alter extraction,
Gold annotations, admission, or scientific records.
"""

from __future__ import annotations

import math
import re
from typing import Any


_ASSOCIATION_FIELDS = (
    "catalyst",
    "catalyst_state",
    "reaction",
    "product",
    "reactant",
    "temperature",
    "pressure",
    "feed",
    "flow",
    "space_velocity",
    "potential",
    "reference_electrode",
    "electrolyte",
    "pH",
    "normalization_basis",
    "duration",
    "time_on_stream",
)


def _normal(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(
            r"\s+",
            " ",
            value.strip()
            .casefold()
            .replace("−", "-")
            .replace("–", "-")
            .replace("◦", "°")
            .replace("º", "°"),
        )
    return value


def _potential_parts(value: Any) -> tuple[float | None, str | None]:
    """Return numeric potential and explicitly reported reference without converting scales."""
    if isinstance(value, dict):
        reference = value.get("reported_reference") or value.get("reference_electrode")
        raw = value.get("raw_potential")
        if isinstance(raw, dict):
            numeric = raw.get("value")
            if isinstance(numeric, (int, float)):
                return float(numeric), _normal(reference) if reference else None
            raw = raw.get("raw_value")
        if raw is None:
            raw = value.get("raw_value")
        numeric, parsed_reference = _potential_parts(raw)
        return numeric, _normal(reference) if reference else parsed_reference
    if isinstance(value, (int, float)):
        return float(value), None
    if not isinstance(value, str):
        return None, None
    text = _normal(value)
    match = re.search(r"(?<![a-z0-9])([+-]?\d+(?:\.\d+)?)", text)
    numeric = float(match.group(1)) if match else None
    compact = re.sub(r"[^a-z0-9]+", "", text)
    reference = None
    for candidate in ("rhe", "she", "nhe"):
        if candidate in compact:
            reference = candidate
            break
    if reference is None and "agagcl" in compact:
        reference = "ag/agcl"
    return numeric, reference


def potential_equal(expected: Any, observed: Any) -> bool:
    """Compare reported potentials by value/reference only; never perform a scale conversion."""
    if _equal(expected, observed):
        return True
    expected_value, expected_reference = _potential_parts(expected)
    observed_value, observed_reference = _potential_parts(observed)
    if expected_value is None or observed_value is None:
        return False
    if not math.isclose(expected_value, observed_value, rel_tol=1e-6, abs_tol=1e-9):
        return False
    if expected_reference is None:
        return True
    return expected_reference == observed_reference


def _feed_signature(value: Any) -> str | None:
    """Map only explicit typed CO2/O2 feed membership to the curated benchmark labels."""
    if isinstance(value, str):
        normalized = _normal(value)
        if normalized in {"pure co2", "o2-containing co2 feed"}:
            return normalized
        return normalized
    if not isinstance(value, list):
        return None
    species = {
        _normal(item.get("species"))
        for item in value
        if isinstance(item, dict) and item.get("species")
    }
    if species == {"co2"}:
        return "pure co2"
    if "co2" in species and "o2" in species:
        return "o2-containing co2 feed"
    return None


def feed_equal(expected: Any, observed: Any) -> bool:
    if _equal(expected, observed):
        return True
    expected_signature = _feed_signature(expected)
    observed_signature = _feed_signature(observed)
    return expected_signature is not None and expected_signature == observed_signature


def _field_value(record: dict[str, Any], field: str) -> Any:
    context = record.get("context") if isinstance(record.get("context"), dict) else {}

    if field == "reference_electrode":
        for mapping in (record, context):
            for alias in ("reference_electrode", "reference", "reported_reference"):
                if mapping.get(alias) is not None:
                    return mapping[alias]
        potential = record.get("potential")
        if isinstance(potential, dict) and potential.get("reported_reference") is not None:
            return potential.get("reported_reference")
        return None

    aliases = {
        "catalyst": ("catalyst", "catalyst_id", "catalyst_ref", "material_ref"),
        "potential": ("potential", "potential_raw", "raw_potential"),
        "temperature": ("temperature", "temperature_c", "operating_temperature"),
        "flow": ("flow", "flow_rate"),
        "duration": ("duration",),
        "time_on_stream": ("time_on_stream", "tos"),
    }.get(field, (field,))
    for mapping in (record, context):
        for alias in aliases:
            if alias in mapping and mapping[alias] is not None:
                value = mapping[alias]
                if isinstance(value, dict) and field != "potential":
                    return value.get("raw_value") or value.get("reported_basis") or value
                return value
    return None


def _equal(expected: Any, observed: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        return math.isclose(float(expected), float(observed), rel_tol=1e-6, abs_tol=1e-9)
    return _normal(expected) == _normal(observed)


def _reported_name_equal(expected: Any, observed: Any) -> bool:
    expected_name = _normal(expected)
    observed_name = _normal(observed)
    if expected_name == observed_name:
        return True
    if isinstance(expected_name, str) and isinstance(observed_name, str):
        return expected_name.removeprefix("commercial ") == observed_name.removeprefix("commercial ")
    return False


def _canonical_unit(value: Any, *, product: str | None = None) -> Any:
    """Normalize display-equivalent unit syntax without converting dimensions."""
    if not isinstance(value, str):
        return value
    unit = _normal(value).replace("²", "2").replace("⁻", "-")
    if product:
        unit = re.sub(re.escape(_normal(product)), "", unit, flags=re.IGNORECASE)
    unit = unit.replace("·", "/")
    unit = re.sub(r"\s*/\s*", "/", unit)
    # Parser/display variants such as h-1 and L-1 mean reciprocal units.
    unit = re.sub(r"\s+([a-z]+)\s*-\s*1\b", r"/\1", unit)
    unit = re.sub(r"\s+([a-z]+)\s*-\s*([2-9][0-9]*)\b", r"/\1\2", unit)
    unit = unit.replace(" ", "")
    parts = [part for part in unit.split("/") if part]
    if len(parts) <= 1:
        return unit
    numerator, denominators = parts[0], sorted(parts[1:])
    return "/".join((numerator, *denominators))


def unit_equal(
    expected: Any,
    observed: Any,
    *,
    expected_product: str | None = None,
    observed_product: str | None = None,
) -> bool:
    """Compare units while allowing an explicitly separated product species label."""
    if _canonical_unit(expected) == _canonical_unit(observed):
        return True
    if not expected_product or not observed_product or not _equal(expected_product, observed_product):
        return False
    return _canonical_unit(expected, product=expected_product) == _canonical_unit(
        observed, product=observed_product
    )


def _reaction_signature(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _normal(value)
    compact = re.sub(r"[^a-z0-9]+", "", normalized)
    if "methanation" in normalized or all(token in compact for token in ("co2", "h2", "ch4")):
        return "co2_methanation"
    return normalized


def reaction_equal(expected: Any, observed: Any) -> bool:
    """Recognize explicit CO2 methanation chemistry as hydrogenation, but nothing broader."""
    if _equal(expected, observed):
        return True
    expected_signature = _reaction_signature(expected)
    observed_signature = _reaction_signature(observed)
    return expected_signature == "hydrogenation" and observed_signature == "co2_methanation"


def metric_match(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Match one metric only when every Gold-asserted association is preserved."""
    for field in ("property", "value"):
        expected_value = expected.get(field)
        if expected_value is not None and not _equal(expected_value, observed.get(field)):
            return False

    expected_product = _field_value(expected, "product")
    observed_product = _field_value(observed, "product")
    if expected.get("unit") is not None and not unit_equal(
        expected.get("unit"),
        observed.get("unit"),
        expected_product=expected_product,
        observed_product=observed_product,
    ):
        return False

    if expected.get("qualifier") is not None and not _equal(expected.get("qualifier"), observed.get("qualifier")):
        return False

    for field in _ASSOCIATION_FIELDS:
        expected_value = _field_value(expected, field)
        if expected_value is None:
            continue
        observed_value = _field_value(observed, field)
        if observed_value is None:
            return False
        if field == "catalyst":
            equal = _reported_name_equal(expected_value, observed_value)
        elif field == "reaction":
            equal = reaction_equal(expected_value, observed_value)
        elif field == "feed":
            equal = feed_equal(expected_value, observed_value)
        elif field == "potential":
            equal = potential_equal(expected_value, observed_value)
        else:
            equal = _equal(expected_value, observed_value)
        if not equal:
            return False
    return True


def observed_metrics(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Project validated CatalysisDocument metrics without discarding typed context."""
    catalysts = {
        item.get("local_id"): item
        for item in document.get("catalysts", [])
        if isinstance(item, dict)
    }
    projected: list[dict[str, Any]] = []
    for group in ("heterogeneous_experiments", "electrocatalysis_experiments"):
        for experiment in document.get(group, []):
            if not isinstance(experiment, dict):
                continue
            catalyst = catalysts.get(experiment.get("catalyst_ref"), {})
            reaction = experiment.get("reaction") if isinstance(experiment.get("reaction"), dict) else {}
            reaction_class = reaction.get("reaction_class")
            reported_reaction = reaction.get("reported_reaction")
            reaction_value = (
                reported_reaction
                if reported_reaction and reaction_class in (None, "", "unknown", "other_heterogeneous")
                else reaction_class or reported_reaction
            )
            context = {
                "catalyst": catalyst.get("reported_name") or catalyst.get("canonical_name"),
                "catalyst_state": catalyst.get("state"),
                "reaction": reaction_value,
                "temperature": _field_value(experiment, "temperature"),
                "pressure": _field_value(experiment, "pressure"),
                "flow": _field_value(experiment, "flow"),
                "space_velocity": _field_value(experiment, "space_velocity"),
                "feed": experiment.get("feed_composition"),
                "electrolyte": experiment.get("electrolyte"),
                "pH": experiment.get("pH"),
            }
            for metric in experiment.get("metrics", []):
                if not isinstance(metric, dict):
                    continue
                item = dict(metric)
                item["context"] = context
                projected.append(item)
    return projected


def score_metric_association(
    gold_record: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    """Score only the independently curated Gold metric associations."""
    observed = observed_metrics(document)
    results = [
        {
            "expected": expected,
            "matched": any(metric_match(expected, candidate) for candidate in observed),
        }
        for expected in gold_record.get("metrics", [])
    ]
    return {
        "expected_count": len(results),
        "matched_count": sum(item["matched"] for item in results),
        "results": results,
    }
