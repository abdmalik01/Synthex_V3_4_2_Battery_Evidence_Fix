"""Offline benchmark utilities for Corrosion V1.

The scorer is deliberately conservative: it does not convert units, reference-electrode
scales, or normalization bases. Gold assertions must be grounded in a selected source
paper before use. This module performs no provider or network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import math
import re
from typing import Iterable

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.explorer import build_archive_explorer
from synthex_platform.scientific_text import normalize_scientific_text
from synthex_platform.extraction.corrosion_units import corrosion_unit_category


def _token(value: object | None) -> str:
    text = normalize_scientific_text(value)
    # Display-only normalization: accept common typography for the same printed unit,
    # but never perform dimensional conversion.
    text = text.replace("·", " ").replace("*", " ")
    text = text.replace("cm^-2", "cm-2").replace("cm^−2", "cm-2")
    text = re.sub(r"\s+", " ", text)
    return text


def _unit_token(value: object | None) -> str:
    """Normalize notation-only unit variants without dimensional conversion.

    ``u`` is a common ASCII surrogate for the micro sign in extracted PDF text, so
    ``uA``, ``µA`` and ``μA`` are treated as the same printed microampere unit.  This
    helper also normalizes inverse-area typography only; it never changes metric
    prefixes or performs scale conversion (for example, mA remains distinct from uA).
    """
    text = (
        _token(value)
        .replace("µ", "u").replace("μ", "u").replace("²", "2")
        .replace("Ω", "ohm").replace("ω", "ohm")
    )
    text = text.replace("/cm2", " cm-2").replace("/cm-2", " cm-2")
    return re.sub(r"\s+", " ", text).strip()


def _material_token(value: object | None) -> str:
    """Normalize harmless typography in material grade names only.

    Scientific PDFs may render a grade such as ``20# steel`` as ``20 # steel``.
    Treat spacing around the grade marker as display typography, while leaving the
    scorer's global token normalization unchanged for units, experiment types, and
    reference electrodes.
    """
    return re.sub(r"\s*#\s*", "#", _token(value))


@dataclass(frozen=True)
class CorrosionExpectedObservation:
    metric: str
    value: float
    unit: str | None
    experiment_type: str | None = None
    record_type: str | None = None
    calculation_type: str | None = None
    material_contains: str | None = None
    treatment_contains: str | None = None
    reference_electrode: str | None = None
    exposure_time: str | None = None
    temperature: str | None = None
    treatment_concentration: str | None = None
    electrolyte_contains: str | None = None
    equivalent_circuit_contains: str | None = None
    reported_term: str | None = None
    data_kind: str | None = None
    element_role: str | None = None
    unit_category: str | None = None
    adsorbate_contains: str | None = None
    surface_contains: str | None = None
    method_contains: str | None = None
    software_contains: str | None = None
    functional_contains: str | None = None
    basis_set_contains: str | None = None
    tolerance_abs: float = 1e-9
    required: bool = True


@dataclass(frozen=True)
class CorrosionExpectedQuarantine:
    """A value that must remain outside canonical records for a specific reason."""

    metric: str
    value: float
    unit: str | None
    reason: str
    tolerance_abs: float = 1e-9


@dataclass(frozen=True)
class CorrosionBenchmarkScore:
    total_required: int
    matched_required: int
    value_matches: int
    scientific_type_matches: int
    association_matches: int
    source_tracking_matches: int
    quarantine_total: int
    quarantine_matches: int
    missed: tuple[dict, ...]
    matched: tuple[dict, ...]

    @property
    def recall(self) -> float:
        return self.matched_required / self.total_required if self.total_required else 1.0

    @property
    def value_accuracy(self) -> float:
        return self.value_matches / self.total_required if self.total_required else 1.0

    @property
    def association_accuracy(self) -> float:
        return self.association_matches / self.total_required if self.total_required else 1.0

    @property
    def scientific_type_accuracy(self) -> float:
        return self.scientific_type_matches / self.total_required if self.total_required else 1.0

    @property
    def source_tracking_coverage(self) -> float:
        return self.source_tracking_matches / self.total_required if self.total_required else 1.0

    @property
    def quarantine_correctness(self) -> float:
        return self.quarantine_matches / self.quarantine_total if self.quarantine_total else 1.0

    @property
    def overall(self) -> float:
        components = [
            self.value_accuracy,
            self.scientific_type_accuracy,
            self.association_accuracy,
            self.source_tracking_coverage,
        ]
        if self.quarantine_total:
            components.append(self.quarantine_correctness)
        return sum(components) / len(components)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload.update({
            "recall": self.recall,
            "value_accuracy": self.value_accuracy,
            "scientific_type_accuracy": self.scientific_type_accuracy,
            "association_accuracy": self.association_accuracy,
            "source_tracking_coverage": self.source_tracking_coverage,
            "quarantine_correctness": self.quarantine_correctness,
            "overall": self.overall,
        })
        return payload


def _numeric_equal(actual: object, expected: float, tolerance_abs: float) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False
    return math.isclose(value, expected, rel_tol=0.0, abs_tol=tolerance_abs)


def _material_match(row: dict, needle: str | None) -> bool:
    if not needle:
        return True
    # Explorer rows store material names as a pipe-delimited display string. Older
    # benchmark code treated that string as an iterable and accidentally compared
    # character-by-character, causing valid material associations to fail.
    value = row.get("material_names")
    if isinstance(value, (list, tuple, set)):
        haystack = " | ".join(str(item) for item in value if item is not None)
    else:
        haystack = str(value or "")
    return _material_token(needle) in _material_token(haystack)


def _row_conditions(row: dict) -> dict:
    direct = row.get("conditions")
    if isinstance(direct, dict):
        return direct
    encoded = row.get("conditions_json")
    if not isinstance(encoded, str) or not encoded.strip():
        return {}
    try:
        payload = json.loads(encoded)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _treatment_match(row: dict, needle: str | None) -> bool:
    if not needle:
        return True
    conditions = _row_conditions(row)
    values: list[str] = []
    for key in ("treatment", "inhibitor", "treatment_name", "inhibitor_name"):
        value = conditions.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in (None, ""))
        elif value not in (None, ""):
            values.append(str(value))
    if not values:
        return False
    haystack = " | ".join(values)
    return _token(needle) in _token(haystack)


def _reference_electrode_match(actual: object | None, expected: str | None) -> bool:
    if not expected:
        return True
    actual_token = _token(actual)
    expected_token = _token(expected)
    if not actual_token:
        return False
    if actual_token == expected_token:
        return True
    # Accept a source-reported abbreviation only when it is literally preserved in
    # parentheses in the longer label; this is textual alias handling, not scale
    # conversion (e.g. SCE <-> saturated calomel electrode (SCE)).
    return f"({expected_token})" in actual_token or f"({actual_token})" in expected_token


def _condition_text(conditions: dict, key: str) -> str:
    value = conditions.get(key)
    if isinstance(value, dict):
        value = value.get("raw_value", value.get("value"))
    return str(value or "")


def _condition_match(conditions: dict, key: str, expected: str | None, *, contains: bool = False) -> bool:
    if not expected:
        return True
    actual = _condition_token(_condition_text(conditions, key))
    wanted = _condition_token(expected)
    return wanted in actual if contains else actual == wanted


def _condition_token(value: object | None) -> str:
    """Normalize notation-only condition variants for benchmark comparison.

    A leading unit coefficient in scientific notation is optional in ordinary
    source typography (``1 x 10^-3 M`` and ``10^-3 M``). This comparison key
    removes only that explicit coefficient; it does not convert units, scale a
    value, or alter archive/evidence text.
    """
    text = _token(value).replace("Ã—", "x").replace("×", "x")
    return re.sub(r"(?<![\d.])1\s*x\s*(?=10\s*\^?\s*[+-]?\d)", "", text)


def _scientific_name_match(actual: object | None, expected: str | None) -> bool:
    """Match a full source name to its explicitly parenthesized abbreviation.

    This is label handling only: ``Indigo blue (IB)`` may match ``IB``, but no
    chemical synonym, descriptor, value, or unit is inferred.
    """
    if not expected:
        return True
    actual_token = _token(actual)
    expected_token = _token(expected)
    if expected_token in actual_token:
        return True
    aliases = {_token(item) for item in re.findall(r"\(([^()]+)\)", str(expected))}
    return actual_token in aliases


def _scientific_type_match(row: dict, expected: CorrosionExpectedObservation) -> bool:
    conditions = _row_conditions(row)
    return all((
        _condition_match(conditions, "reported_term", expected.reported_term),
        _condition_match(conditions, "data_kind", expected.data_kind),
        _condition_match(conditions, "element_role", expected.element_role),
        not expected.unit_category
        or corrosion_unit_category(row.get("unit")) == expected.unit_category,
    ))


def _association_match(row: dict, expected: CorrosionExpectedObservation) -> bool:
    if expected.record_type and _token(row.get("record_type")) != _token(expected.record_type):
        return False
    if expected.experiment_type and _token(row.get("experiment_type")) != _token(expected.experiment_type):
        return False
    if expected.calculation_type and _token(row.get("calculation_type")) != _token(expected.calculation_type):
        return False
    if not _material_match(row, expected.material_contains):
        return False
    if not _treatment_match(row, expected.treatment_contains):
        return False
    if expected.reference_electrode:
        actual = row.get("reference_electrode")
        if not actual:
            conditions = _row_conditions(row)
            actual = conditions.get("reference_electrode")
        if not _reference_electrode_match(actual, expected.reference_electrode):
            return False
    conditions = _row_conditions(row)
    if not _scientific_name_match(
        conditions.get("adsorbate_or_inhibitor"), expected.adsorbate_contains
    ):
        return False
    for key, wanted in (
        ("surface", expected.surface_contains),
        ("software", expected.software_contains),
        ("functional", expected.functional_contains),
        ("basis_set", expected.basis_set_contains),
    ):
        if not _condition_match(conditions, key, wanted, contains=True):
            return False
    if expected.method_contains and _token(expected.method_contains) not in _token(row.get("method")):
        return False
    if not _condition_match(conditions, "exposure_time", expected.exposure_time):
        return False
    if not _condition_match(conditions, "temperature", expected.temperature):
        return False
    if not (
        _condition_match(conditions, "inhibitor_concentration", expected.treatment_concentration)
        or _condition_match(conditions, "treatment_concentration", expected.treatment_concentration)
    ):
        return False
    if not _condition_match(
        conditions, "electrolyte", expected.electrolyte_contains, contains=True
    ):
        return False
    if not _condition_match(
        conditions, "equivalent_circuit", expected.equivalent_circuit_contains, contains=True
    ):
        return False
    return True


def _quarantine_entries(value: object):
    if isinstance(value, dict):
        quarantine = value.get("quarantine")
        if isinstance(quarantine, list):
            yield from (item for item in quarantine if isinstance(item, dict))
        for child in value.values():
            yield from _quarantine_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _quarantine_entries(child)


def _quarantined_metrics(archive: SynthexArchive):
    for payload in archive.domain_payloads:
        data = payload.model_dump(mode="python")
        for entry in _quarantine_entries(data):
            obj = entry.get("object")
            if not isinstance(obj, dict):
                continue
            if "property" in obj and isinstance(obj.get("quantity"), dict):
                yield entry, obj
            for metric in obj.get("metrics", []) if isinstance(obj.get("metrics"), list) else []:
                if isinstance(metric, dict) and isinstance(metric.get("quantity"), dict):
                    yield entry, metric


def _source_tracked(row: dict) -> bool:
    return bool(
        row.get("source_title")
        and row.get("source_page")
        and row.get("evidence_snippet")
        and row.get("evidence_origin") in {"native_text", "table_reported", "ocr_extracted"}
    )


def score_corrosion_archive(
    archive: SynthexArchive,
    expected: Iterable[CorrosionExpectedObservation],
    expected_quarantine: Iterable[CorrosionExpectedQuarantine] = (),
) -> CorrosionBenchmarkScore:
    """Score canonical corrosion observations against paper-grounded gold assertions.

    Matching requires the same property and same printed unit representation after only
    harmless typography normalization. No unit conversion or potential conversion occurs.
    """
    if archive.metadata.domain != "corrosion":
        raise ValueError("Corrosion benchmark scorer requires a corrosion archive.")

    rows = list(build_archive_explorer(archive, include_quarantined=False).results)
    required = [item for item in expected if item.required]
    matched_records: list[dict] = []
    missed_records: list[dict] = []
    matched_required = value_matches = scientific_type_matches = 0
    association_matches = source_tracking_matches = 0

    for assertion in required:
        property_rows = [row for row in rows if _token(row.get("metric")) == _token(assertion.metric)]
        unit_rows = [
            row for row in property_rows
            if assertion.unit is None or _unit_token(row.get("unit")) == _unit_token(assertion.unit)
        ]
        value_rows = [
            row for row in unit_rows
            if _numeric_equal(row.get("value"), assertion.value, assertion.tolerance_abs)
        ]
        scientific_type_rows = [
            row for row in value_rows if _scientific_type_match(row, assertion)
        ]
        association_rows = [
            row for row in scientific_type_rows if _association_match(row, assertion)
        ]
        chosen = next((row for row in association_rows if _source_tracked(row)), None)
        if chosen is None and association_rows:
            chosen = association_rows[0]
        elif chosen is None and value_rows:
            chosen = value_rows[0]

        if value_rows:
            value_matches += 1
        if scientific_type_rows:
            scientific_type_matches += 1
        if association_rows:
            association_matches += 1
        if chosen is not None and _source_tracked(chosen):
            source_tracking_matches += 1
        if association_rows:
            matched_required += 1
            matched_records.append({
                "expected": asdict(assertion),
                "record_id": chosen.get("record_id") if chosen else None,
                "source_tracked": _source_tracked(chosen) if chosen else False,
            })
        else:
            missed_records.append({
                "expected": asdict(assertion),
                "property_candidates": len(property_rows),
                "unit_candidates": len(unit_rows),
                "value_candidates": len(value_rows),
                "scientific_type_candidates": len(scientific_type_rows),
            })

    quarantine_assertions = list(expected_quarantine)
    quarantine_matches = 0
    quarantine_rows = list(_quarantined_metrics(archive))
    for assertion in quarantine_assertions:
        canonical_collision = any(
            _token(row.get("metric")) == _token(assertion.metric)
            and (assertion.unit is None or _unit_token(row.get("unit")) == _unit_token(assertion.unit))
            and _numeric_equal(row.get("value"), assertion.value, assertion.tolerance_abs)
            for row in rows
        )
        quarantined = any(
            entry.get("reason") == assertion.reason
            and _token(metric.get("property")) == _token(assertion.metric)
            and (
                assertion.unit is None
                or _unit_token((metric.get("quantity") or {}).get("unit")) == _unit_token(assertion.unit)
            )
            and _numeric_equal((metric.get("quantity") or {}).get("value"), assertion.value, assertion.tolerance_abs)
            for entry, metric in quarantine_rows
        )
        if not canonical_collision and quarantined:
            quarantine_matches += 1

    return CorrosionBenchmarkScore(
        total_required=len(required),
        matched_required=matched_required,
        value_matches=value_matches,
        scientific_type_matches=scientific_type_matches,
        association_matches=association_matches,
        source_tracking_matches=source_tracking_matches,
        quarantine_total=len(quarantine_assertions),
        quarantine_matches=quarantine_matches,
        missed=tuple(missed_records),
        matched=tuple(matched_records),
    )
