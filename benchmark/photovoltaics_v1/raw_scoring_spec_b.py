"""Schema-tolerant scoring for an initial PV-SPEC-B provider payload."""

from __future__ import annotations

from typing import Any


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
    text = _text(value).casefold().replace("−", "-")
    if "ternary" in text:
        return "ternary"
    if "pm6:o-btp-ec9" in text or "pm6:o-btp" in text:
        return "pm6_o_btp_ec9"
    if "pm6:btp-ec9" in text or "pm6:btp" in text:
        return "pm6_btp_ec9"
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def score_raw_spec_b(payload: dict, expected_series: list[dict]) -> dict:
    devices = _objects(payload, "devices")
    device_by_variant = {_variant(item): item for item in devices if _variant(item)}
    device_ref_variant = {
        str(item.get("local_id") or item.get("device_id")): variant
        for variant, item in device_by_variant.items()
    }
    experiments = _objects(payload, "experiments")
    outputs_by_variant: dict[str, list[dict]] = {item["variant"]: [] for item in expected_series}
    for experiment in experiments:
        refs = experiment.get("device_refs") or experiment.get("device_ids") or []
        if isinstance(refs, str):
            refs = [refs]
        variant = next((device_ref_variant.get(str(ref)) for ref in refs if device_ref_variant.get(str(ref))), None)
        variant = variant or _variant(experiment)
        outputs = experiment.get("outputs", [])
        if isinstance(outputs, dict):
            outputs = [outputs]
        if variant in outputs_by_variant:
            outputs_by_variant[variant].extend(item for item in outputs if isinstance(item, dict))

    exact_points = 0
    wavelength_context = 0
    workbook_evidence = 0
    rows = []
    for expected in expected_series:
        expected_map = {float(point["wavelength_nm"]): float(point["eqe_percent"]) for point in expected["points"]}
        found = outputs_by_variant[expected["variant"]]
        matched_wavelengths = set()
        for output in found:
            if output.get("property") not in {"external_quantum_efficiency", "incident_photon_to_current_efficiency"}:
                continue
            conditions = output.get("conditions", {}) if isinstance(output.get("conditions"), dict) else {}
            wavelength = _number(conditions.get("wavelength"))
            value = _number(output.get("value"))
            if wavelength in expected_map and value == expected_map[wavelength]:
                exact_points += 1
                matched_wavelengths.add(wavelength)
            if wavelength is not None and str(conditions.get("wavelength_unit", "")).casefold() == "nm":
                wavelength_context += 1
            evidence = output.get("evidence", [])
            if isinstance(evidence, dict):
                evidence = [evidence]
            if any(
                isinstance(item, dict)
                and "fig. 3b" in _text(item).casefold()
                and ("cell" in _text(item).casefold() or "workbook" in _text(item).casefold())
                for item in evidence
            ):
                workbook_evidence += 1
        rows.append({
            "variant": expected["variant"],
            "device_found": expected["variant"] in device_by_variant,
            "expected_points": len(expected_map),
            "exact_points": len(matched_wavelengths),
            "provider_outputs": len(found),
        })
    total = sum(len(item["points"]) for item in expected_series)
    return {
        "case_id": "PV-SPEC-B",
        "initial_payload_scored": True,
        "rows": rows,
        "scores": {
            "device_identity": f"{len(device_by_variant)}/3",
            "exact_spectral_points": f"{exact_points}/{total}",
            "wavelength_context": f"{wavelength_context}/{total}",
            "workbook_cell_evidence": f"{workbook_evidence}/{total}",
        },
        "safety": {
            "device_variants_collapsed": len(device_by_variant) < 3,
            "spectral_points_missing": exact_points < total,
            "percentages_fractionalized": any(
                _number(output.get("value")) is not None and 0 < _number(output.get("value")) <= 1
                for outputs in outputs_by_variant.values() for output in outputs
                if output.get("property") == "external_quantum_efficiency"
            ),
        },
    }
