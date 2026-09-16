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


def _token(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    text = text.replace("−", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
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
    text = _token(value).replace("µ", "u").replace("μ", "u").replace("²", "2")
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
    unit: str
    experiment_type: str | None = None
    material_contains: str | None = None
    treatment_contains: str | None = None
    reference_electrode: str | None = None
    tolerance_abs: float = 1e-9
    required: bool = True


@dataclass(frozen=True)
class CorrosionBenchmarkScore:
    total_required: int
    matched_required: int
    value_matches: int
    association_matches: int
    source_tracking_matches: int
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
    def source_tracking_coverage(self) -> float:
        return self.source_tracking_matches / self.total_required if self.total_required else 1.0

    @property
    def overall(self) -> float:
        return (self.value_accuracy + self.association_accuracy + self.source_tracking_coverage) / 3.0

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload.update({
            "recall": self.recall,
            "value_accuracy": self.value_accuracy,
            "association_accuracy": self.association_accuracy,
            "source_tracking_coverage": self.source_tracking_coverage,
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


def _association_match(row: dict, expected: CorrosionExpectedObservation) -> bool:
    if expected.experiment_type and _token(row.get("experiment_type")) != _token(expected.experiment_type):
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
    return True


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
    matched_required = value_matches = association_matches = source_tracking_matches = 0

    for assertion in required:
        property_rows = [row for row in rows if _token(row.get("metric")) == _token(assertion.metric)]
        unit_rows = [row for row in property_rows if _unit_token(row.get("unit")) == _unit_token(assertion.unit)]
        value_rows = [
            row for row in unit_rows
            if _numeric_equal(row.get("value"), assertion.value, assertion.tolerance_abs)
        ]
        association_rows = [row for row in value_rows if _association_match(row, assertion)]
        chosen = next((row for row in association_rows if _source_tracked(row)), None)
        if chosen is None and association_rows:
            chosen = association_rows[0]
        elif chosen is None and value_rows:
            chosen = value_rows[0]

        if value_rows:
            value_matches += 1
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
            })

    return CorrosionBenchmarkScore(
        total_required=len(required),
        matched_required=matched_required,
        value_matches=value_matches,
        association_matches=association_matches,
        source_tracking_matches=source_tracking_matches,
        missed=tuple(missed_records),
        matched=tuple(matched_records),
    )
