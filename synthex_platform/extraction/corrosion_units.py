"""Dimension-category checks for source-reported corrosion quantities.

The helpers in this module classify unit text only. They intentionally perform no
numeric conversion: in particular, mass-loss rates and penetration-depth rates stay
distinct unless a separate, provenance-complete derivation contract is introduced.
"""

from __future__ import annotations

import re
from typing import Literal

from synthex_platform.scientific_text import normalize_scientific_text


CorrosionUnitCategory = Literal[
    "mass",
    "area",
    "time",
    "mass_per_area",
    "mass_loss_rate",
    "penetration_rate",
    "length",
    "density",
    "percent",
    "unknown",
]


def _unit_token(unit: str | None) -> str:
    text = normalize_scientific_text(unit or "").casefold()
    text = (
        text.replace("µ", "u")
        .replace("μ", "u")
        .replace("²", "2")
        .replace("³", "3")
        .replace("·", " ")
        .replace("−", "-")
    )
    text = re.sub(r"\bper\b", "/", text)
    text = text.replace("years", "year").replace("yrs", "year").replace("yr", "year")
    text = text.replace("days", "day").replace("hours", "h").replace("hour", "h")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def corrosion_unit_category(unit: str | None) -> CorrosionUnitCategory:
    """Return a dimensional category without converting the reported value."""
    token = _unit_token(unit)
    if not token:
        return "unknown"
    compact = token.replace(" ", "").replace("^", "")
    if compact in {"%", "percent"}:
        return "percent"
    if compact in {"mg", "g", "kg", "ug"}:
        return "mass"
    if compact in {"cm2", "m2", "mm2"}:
        return "area"
    if compact in {"h", "day", "s", "min", "year", "y"}:
        return "time"
    if re.fullmatch(r"(?:g|mg|kg|ug)/(?:cm2|m2|mm2)", compact) or re.fullmatch(
        r"(?:g|mg|kg|ug)(?:cm|m|mm)-2", compact
    ):
        return "mass_per_area"
    if (
        re.fullmatch(r"(?:g|mg|kg|ug)/(?:cm2|m2|mm2)/(?:h|day|s|min|year|y)", compact)
        or re.fullmatch(r"(?:g|mg|kg|ug)(?:cm|m|mm)-2(?:h|day|s|min|year|y)-1", compact)
    ):
        return "mass_loss_rate"
    if compact == "mpy" or re.fullmatch(r"(?:mm|um|cm|mil)/(?:year|y)", compact):
        return "penetration_rate"
    if compact in {"mm", "um", "cm", "m", "mil"}:
        return "length"
    if re.fullmatch(r"(?:g|mg|kg)/(?:cm3|m3|mm3)", compact):
        return "density"
    return "unknown"


def corrosion_metric_unit_is_compatible(property_name: str, unit: str | None) -> bool:
    """Check only categories with an explicit gravimetric Corrosion V1 contract."""
    category = corrosion_unit_category(unit)
    if category == "unknown":
        return True
    allowed = {
        "initial_mass": {"mass"},
        "final_mass": {"mass"},
        "mass_loss": {"mass", "mass_per_area"},
        "corrosion_rate": {"mass_loss_rate", "penetration_rate"},
        "penetration_rate": {"penetration_rate"},
        "penetration_depth": {"length"},
        "inhibition_efficiency": {"percent"},
        "protection_efficiency": {"percent"},
    }.get(property_name)
    return True if allowed is None else category in allowed
