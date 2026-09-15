from __future__ import annotations

import json
import re
from typing import Any

from .battery_models import BatteryDocument


def _strip_markdown_fence(text: str) -> str:
    """Remove a single outer Markdown code fence without touching JSON content."""
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].strip().lower() in {"```", "```json"}:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _quantity_to_int(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    numeric = value.get("value")
    if isinstance(numeric, (int, float)) and float(numeric).is_integer():
        return int(numeric)
    raw = value.get("raw_value")
    if isinstance(raw, str):
        match = re.search(r"[-+]?\d+", raw)
        if match:
            return int(match.group(0))
    return value


def _quantity_to_string(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    raw = value.get("raw_value")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    numeric = value.get("value")
    if numeric is not None:
        unit = value.get("unit")
        return f"{numeric} {unit}".strip() if unit else str(numeric)
    return value


def normalize_battery_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize only schema-shape drift that preserves the provider's reported meaning.

    No scientific value is derived, converted, repaired, or invented here. Structured quantity
    objects are collapsed only where the canonical BatteryDocument field is explicitly an int
    or string and the same raw/numeric value is already present in provider output.
    """
    cleaned = dict(payload)

    protocols = cleaned.get("shared_protocols")
    if isinstance(protocols, list):
        normalized_protocols = []
        for protocol in protocols:
            if not isinstance(protocol, dict):
                normalized_protocols.append(protocol)
                continue
            item = dict(protocol)
            testing = item.get("electrochemical_testing")
            if isinstance(testing, dict):
                testing = dict(testing)
                testing["long_term_cycles"] = _quantity_to_int(testing.get("long_term_cycles"))
                testing["long_term_c_rate"] = _quantity_to_string(testing.get("long_term_c_rate"))
                item["electrochemical_testing"] = testing
            normalized_protocols.append(item)
        cleaned["shared_protocols"] = normalized_protocols

    groups = cleaned.get("battery_groups")
    if isinstance(groups, list):
        normalized_groups = []
        for group in groups:
            if not isinstance(group, dict):
                normalized_groups.append(group)
                continue
            item = dict(group)
            points = item.get("performance_points")
            if isinstance(points, list):
                normalized_points = []
                for point in points:
                    if not isinstance(point, dict):
                        normalized_points.append(point)
                        continue
                    point = dict(point)
                    point["cycle"] = _quantity_to_int(point.get("cycle"))
                    point["c_rate"] = _quantity_to_string(point.get("c_rate"))
                    normalized_points.append(point)
                item["performance_points"] = normalized_points
            normalized_groups.append(item)
        cleaned["battery_groups"] = normalized_groups

    return cleaned


def parse_battery_document_json(output_text: str) -> BatteryDocument:
    """Parse Gemini JSON with conservative wrapper/shape normalization only."""
    candidate = _strip_markdown_fence(output_text)
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Battery extraction output must be one JSON object.")
    return BatteryDocument.model_validate(normalize_battery_payload(payload))
