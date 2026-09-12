from __future__ import annotations

from .battery_models import BatteryQuantity


def normalize_battery_quantity(q: BatteryQuantity | None) -> tuple[float | None, str | None]:
    if q is None or q.value is None:
        return None, None
    unit = (q.unit or "").strip().replace("μ", "µ")
    aliases = {
        "°c": "°C", "c": "°C",
        "a": "A", "ma": "mA",
        "v": "V", "mv": "mV",
        "hz": "Hz", "khz": "kHz", "mhz": "MHz",
        "s": "s", "sec": "s", "seconds": "s", "min": "min", "h": "h", "hr": "h",
        "mmah/g": "mAh/g", "mah/g": "mAh/g", "mah g−1": "mAh/g", "mah g-1": "mAh/g",
        "cm2/s": "cm²/s", "cm²/s": "cm²/s", "cm 2 s−1": "cm²/s", "cm2 s-1": "cm²/s",
        "mV/s": "mV/s", "mv/s": "mV/s", "%": "%", "wt%": "%",
        "mg/cm2": "mg/cm²", "mg/cm²": "mg/cm²", "mpa": "MPa", "mm": "mm", "µl": "µL", "ul": "µL",
    }
    key = unit.lower()
    canon = aliases.get(key, unit or None)
    value = q.value
    if canon == "mA":
        return value / 1000.0, "A"
    if canon == "mV":
        return value / 1000.0, "V"
    if canon == "kHz":
        return value * 1000.0, "Hz"
    if canon == "MHz":
        return value * 1_000_000.0, "Hz"
    if canon == "min":
        return value * 60.0, "s"
    if canon == "h":
        return value * 3600.0, "s"
    if canon == "mV/s":
        return value / 1000.0, "V/s"
    return value, canon
