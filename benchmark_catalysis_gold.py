"""Scientific, association-aware scoring helpers for Catalysis V1 Stage 3."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable


REQUIRED_GOLD_FIELDS = (
    "benchmark_id", "source", "expected_route", "expected_subtypes", "expected_scope_status",
    "catalysts", "preparations", "characterizations", "experiments", "stability_tests",
    "calculations", "ownership_expectation", "admission_expectation", "curation",
)

ASSOCIATION_FIELDS = (
    "catalyst", "catalyst_state", "reaction", "product", "temperature", "pressure", "feed",
    "flow", "space_velocity", "potential", "reference_electrode", "electrolyte", "pH",
    "normalization_basis", "duration", "time_on_stream",
)

_FIELD_ALIASES = {
    "catalyst": ("catalyst", "catalyst_id", "catalyst_ref", "material_ref"),
    "reference_electrode": ("reference_electrode", "reference", "reported_reference"),
    "potential": ("potential", "potential_raw", "raw_potential"),
    "temperature": ("temperature", "temperature_c", "operating_temperature"),
    "flow": ("flow", "flow_rate"),
    "duration": ("duration",),
    "time_on_stream": ("time_on_stream", "tos"),
}

_DFT_PROPERTIES = {
    "adsorption_energy", "adsorption_free_energy", "reaction_free_energy", "activation_barrier",
    "transition_state_energy", "d_band_center", "work_function", "bader_charge",
    "charge_density_difference", "dos_pdos", "surface_energy", "vacancy_formation_energy",
    "binding_energy", "limiting_potential", "theoretical_overpotential",
}


def validate_gold_record(record: dict[str, Any]) -> dict[str, Any]:
    """Reject templates and require independently source-grounded benchmark metadata."""
    missing_fields = [
        field for field in REQUIRED_GOLD_FIELDS
        if field not in record or record.get(field) in (None, "", {})
    ]
    curation = record.get("curation") if isinstance(record.get("curation"), dict) else {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    errors = []
    if curation.get("source_grounded") is not True:
        errors.append("curation.source_grounded must be true")
    if curation.get("model_output_used") is not False:
        errors.append("curation.model_output_used must be false")
    for field in ("filename", "title", "doi", "year", "checksum"):
        if source.get(field) in (None, ""):
            errors.append(f"source.{field} is required")
    return {
        "valid": not missing_fields and not errors,
        "field_count": len(record),
        "required_fields": list(REQUIRED_GOLD_FIELDS),
        "missing_fields": missing_fields,
        "errors": errors,
    }


def _normal(value: Any) -> Any:
    if isinstance(value, str):
        # Native PDF parsers use several visually equivalent degree/minus glyphs.
        # This normalization is display-only for scoring and never changes the
        # extracted scientific record.
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
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normal(item) for item in value]
    return value


def _field_value(record: dict[str, Any], field: str) -> Any:
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    aliases = _FIELD_ALIASES.get(field, (field,))
    for mapping in (record, context):
        for alias in aliases:
            if alias in mapping and mapping[alias] is not None:
                value = mapping[alias]
                if isinstance(value, dict):
                    return value.get("raw_value") or value.get("reported_basis") or value
                return value
    return None


def _equal(expected: Any, observed: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        return math.isclose(float(expected), float(observed), rel_tol=1e-6, abs_tol=1e-9)
    return _normal(expected) == _normal(observed)


def _unit_equal(expected: Any, observed: Any) -> bool:
    def canonical(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        unit = _normal(value).replace("²", "2").replace("⁻", "-")
        unit = re.sub(r"\s*[/·]\s*", "/", unit)
        unit = re.sub(r"\s+([a-z]+)-([0-9]+)", r"/\1\2", unit)
        return unit.replace(" ", "")

    return canonical(expected) == canonical(observed)


def _reported_name_equal(expected: Any, observed: Any) -> bool:
    expected_name = _normal(expected)
    observed_name = _normal(observed)
    if expected_name == observed_name:
        return True
    if isinstance(expected_name, str) and isinstance(observed_name, str):
        # "commercial" describes provenance, not a different catalyst identity.
        return expected_name.removeprefix("commercial ") == observed_name.removeprefix("commercial ")
    return False


def contextual_value_match(
    expected: dict[str, Any],
    observed: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> bool:
    """Match a value only when every asserted scientific association is present and equal."""
    expected_context = dict(context or {})
    expected_context.update(expected.get("context") or {})
    expected_record = {**expected, "context": expected_context}
    for field in ("property", "unit", "value"):
        expected_value = expected.get(field)
        if expected_value is None:
            continue
        observed_value = observed.get(field)
        comparison = _unit_equal if field == "unit" else _equal
        if observed_value is None or not comparison(expected_value, observed_value):
            return False
    for field in ASSOCIATION_FIELDS:
        expected_value = _field_value(expected_record, field)
        if expected_value is None:
            continue
        observed_value = _field_value(observed, field)
        comparison = _reported_name_equal if field == "catalyst" else _equal
        if observed_value is None or not comparison(expected_value, observed_value):
            return False
    return True


def match_catalyst_identity(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Require identity, variant/state, and component roles when the gold asserts them."""
    for field in ("reported_name", "formula", "state", "variant_of"):
        value = expected.get(field)
        comparison = _reported_name_equal if field == "reported_name" else _equal
        if value is not None and not comparison(value, observed.get(field)):
            return False
    expected_components = {
        (_normal(item.get("role")), _normal(item.get("reported_name") or item.get("formula")))
        for item in expected.get("components", []) if isinstance(item, dict)
    }
    observed_components = {
        (_normal(item.get("role")), _normal(item.get("reported_name") or item.get("formula")))
        for item in observed.get("components", []) if isinstance(item, dict)
    }
    return expected_components.issubset(observed_components)


def match_product_specific_metric(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    required = {key: expected[key] for key in ("product", "normalization_basis", "potential", "reference_electrode") if expected.get(key) is not None}
    return contextual_value_match(expected, observed, required)


def match_stability_association(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return contextual_value_match(expected, observed, {
        key: expected[key]
        for key in ("catalyst", "temperature", "duration", "time_on_stream", "potential")
        if expected.get(key) is not None
    })


def canonical_precision(true_positives: int, false_positives: int, false_negatives: int = 0) -> float:
    """Canonical precision; false negatives are reported separately by design."""
    del false_negatives
    denominator = true_positives + false_positives
    return round(true_positives / denominator, 3) if denominator else 0.0


def canonical_admission_counts(decisions: Iterable[dict[str, Any]]) -> dict[str, int | float]:
    counts = {
        "true_canonical_admissions": 0,
        "false_canonical_admissions": 0,
        "correct_quarantines": 0,
        "incorrect_quarantines": 0,
    }
    for decision in decisions:
        expected = decision.get("expected")
        observed = decision.get("observed")
        if expected == "canonical" and observed == "canonical":
            counts["true_canonical_admissions"] += 1
        elif expected != "canonical" and observed == "canonical":
            counts["false_canonical_admissions"] += 1
        elif expected != "canonical" and observed != "canonical":
            counts["correct_quarantines"] += 1
        elif expected == "canonical" and observed != "canonical":
            counts["incorrect_quarantines"] += 1
    counts["canonical_precision"] = canonical_precision(
        counts["true_canonical_admissions"], counts["false_canonical_admissions"]
    )
    return counts


def review_contamination_count(items: list[dict[str, Any]]) -> int:
    """Count non-focal review/cited values incorrectly admitted as canonical."""
    non_focal = {"cited_prior_work", "review_summary", "comparison_table", "background", "example", "unknown"}
    return sum(
        1 for item in items
        if isinstance(item, dict)
        and item.get("admission_status") == "canonical"
        and item.get("ownership") in non_focal
    )


def detect_dft_leakage(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict) or record.get("record_type") == "CalculationRecord":
        return False
    property_name = str(record.get("property") or "")
    calculation = record.get("calculation") if isinstance(record.get("calculation"), dict) else {}
    return property_name in _DFT_PROPERTIES or str(calculation.get("method") or "").casefold() in {"dft", "first_principles"}


def detect_potential_conversion_violation(potential_record: dict[str, Any]) -> bool:
    converted = potential_record.get("converted_potential")
    if converted is None:
        return False
    status = potential_record.get("conversion_status")
    return status != "author_reported"


def referential_integrity_violations(document: dict[str, Any]) -> list[str]:
    """Report dangling local references in a CatalysisDocument-shaped payload."""
    catalyst_ids = {item.get("local_id") for item in document.get("catalysts", []) if isinstance(item, dict)}
    experiment_ids = {
        item.get("experiment_id")
        for group in ("heterogeneous_experiments", "electrocatalysis_experiments")
        for item in document.get(group, []) if isinstance(item, dict)
    }
    violations: list[str] = []

    def check(ref: Any, allowed: set, path: str) -> None:
        if ref is not None and ref not in allowed:
            violations.append(f"{path}: dangling reference {ref}")

    for index, catalyst in enumerate(document.get("catalysts", [])):
        if isinstance(catalyst, dict):
            check(catalyst.get("state_parent_ref"), catalyst_ids, f"catalysts[{index}].state_parent_ref")
            check(catalyst.get("variant_of"), catalyst_ids, f"catalysts[{index}].variant_of")
    for group in ("preparations", "characterizations"):
        for index, item in enumerate(document.get(group, [])):
            if isinstance(item, dict):
                check(item.get("material_ref"), catalyst_ids, f"{group}[{index}].material_ref")
    for group in ("heterogeneous_experiments", "electrocatalysis_experiments"):
        for index, item in enumerate(document.get(group, [])):
            if isinstance(item, dict):
                check(item.get("catalyst_ref"), catalyst_ids, f"{group}[{index}].catalyst_ref")
    for index, item in enumerate(document.get("stability_tests", [])):
        if isinstance(item, dict):
            check(item.get("experiment_ref"), experiment_ids, f"stability_tests[{index}].experiment_ref")
            check(item.get("catalyst_state_ref"), catalyst_ids, f"stability_tests[{index}].catalyst_state_ref")
    for index, item in enumerate(document.get("calculations", [])):
        if isinstance(item, dict):
            for ref_index, ref in enumerate(item.get("material_refs", [])):
                check(ref, catalyst_ids, f"calculations[{index}].material_refs[{ref_index}]")
    return violations
