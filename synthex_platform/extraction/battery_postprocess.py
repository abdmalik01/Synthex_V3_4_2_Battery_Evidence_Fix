from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from .battery_models import BatteryDocument, SharedBatteryProtocol


PROTOCOL_FIELDS = (
    "charge_protocol",
    "discharge_protocol",
    "impedance_protocol",
    "electrochemical_testing",
    "electrode_fabrication",
    "cell_assembly",
)


def _signature(payload: dict) -> str | None:
    if not any(payload.values()):
        return None
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def deduplicate_shared_protocols(doc: BatteryDocument) -> BatteryDocument:
    """Promote exactly repeated group-level protocol components to shared records.

    Components are compared independently and only byte-equivalent validated payloads
    shared by the same groups are bundled. Sample-specific differences remain inline.
    """
    result = deepcopy(doc)
    existing = {p.protocol_id: p for p in result.shared_protocols}
    promotion_bundles: dict[tuple[int, ...], dict] = {}

    for field in PROTOCOL_FIELDS:
        component_buckets: dict[str, list[int]] = {}
        component_values: dict[str, object] = {}
        for index, group in enumerate(result.battery_groups):
            component = getattr(group, field)
            if component is None:
                continue
            payload = component.model_dump(exclude_none=True)
            sig = _signature({field: payload})
            if sig:
                component_buckets.setdefault(sig, []).append(index)
                component_values[sig] = component
        for sig, indices in component_buckets.items():
            if len(indices) >= 2:
                promotion_bundles.setdefault(tuple(indices), {})[field] = component_values[sig]

    for index_tuple, components in promotion_bundles.items():
        indices = list(index_tuple)
        payload = {
            field: component.model_dump(exclude_none=True)
            for field, component in components.items()
        }
        sig = _signature(payload)
        pid = f"shared_protocol_{sig}"
        if pid not in existing:
            first = result.battery_groups[indices[0]]
            protocol = SharedBatteryProtocol(
                protocol_id=pid,
                name="Shared battery test protocol",
                **components,
                evidence=first.evidence[:1],
            )
            result.shared_protocols.append(protocol)
            existing[pid] = protocol
        for i in indices:
            group = result.battery_groups[i]
            if pid not in group.protocol_refs:
                group.protocol_refs.append(pid)
            for field in components:
                setattr(group, field, None)
    return result


def apply_scientific_guardrails(doc: BatteryDocument) -> BatteryDocument:
    """Conservative deterministic checks for common LLM over-interpretations.

    These checks do not invent replacements. They either remove an unsupported numeric
    inference or add an extraction note so downstream quality scoring can see the issue.
    """
    result = deepcopy(doc)

    def _qualitative_only(q):
        return bool(q and q.raw_value and not any(ch.isdigit() for ch in q.raw_value))

    ambiguous_ratios = []
    for material in result.materials:
        if material.synthesis and material.synthesis.precursor_ratio_raw:
            ambiguous_ratios.extend(re.findall(
                r"\d+(?:\.\d+){2,}(?::\d+)+",
                material.synthesis.precursor_ratio_raw,
            ))
    speculative_markers = ("probably means", "likely means", "intended as", "error for")
    for index, note in enumerate(result.extraction_notes):
        lowered = note.lower()
        ratio = next((value for value in ambiguous_ratios if value in note), None)
        if ratio and any(marker in lowered for marker in speculative_markers):
            result.extraction_notes[index] = (
                f"Ambiguous precursor ratio preserved verbatim as '{ratio}'; "
                "no corrected ratio was inferred."
            )

    # Do not convert qualitative temperature labels into invented numeric temperatures.
    # Numeric-only step labels are IDs/order markers, not scientifically meaningful process names.
    for material in result.materials:
        if material.synthesis:
            for step in material.synthesis.steps:
                raw_step_name = (step.step or "").strip()
                if raw_step_name and re.fullmatch(r"\d+(?:\.\d+)?", raw_step_name):
                    step.step = f"synthesis step {raw_step_name}"
                    result.extraction_notes.append(
                        f"Archive hygiene: numeric synthesis step label '{raw_step_name}' preserved as ordered label "
                        f"'{step.step}' instead of treating it as a process name."
                    )
                if _qualitative_only(step.temperature) and step.temperature.value is not None:
                    raw = step.temperature.raw_value
                    step.temperature.value = None
                    step.temperature.unit = None
                    step.temperature.qualifier = "unknown"
                    result.extraction_notes.append(
                        f"Guardrail: removed unsupported numeric temperature inferred from qualitative source value '{raw}'."
                    )
                if step.atmosphere and step.atmosphere.strip().lower() in {
                    "water bath", "oil bath", "oven", "furnace", "tube furnace", "hot plate"
                }:
                    bad = step.atmosphere
                    step.atmosphere = None
                    result.extraction_notes.append(
                        f"Guardrail: '{bad}' is an apparatus/heating medium, not an explicitly reported atmosphere."
                    )

    for protocol in result.shared_protocols:
        et = protocol.electrochemical_testing
        if et and _qualitative_only(et.temperature) and et.temperature.value is not None:
            raw = et.temperature.raw_value
            et.temperature.value = None
            et.temperature.unit = None
            et.temperature.qualifier = "unknown"
            result.extraction_notes.append(
                f"Guardrail: removed unsupported numeric temperature inferred from qualitative source value '{raw}'."
            )

    for group in result.battery_groups:
        for conflict in group.condition_conflicts:
            if conflict.status != "conflicted" or conflict.resolved_value is not None:
                continue
            field = conflict.field.strip().lower().replace("-", "_")
            if field == "c_rate":
                reported = {re.sub(r"\s+", "", item.value).lower() for item in conflict.reported_values}
                cleared = []
                for point in group.performance_points:
                    if point.c_rate and re.sub(r"\s+", "", point.c_rate).lower() in reported:
                        cleared.append(point.c_rate)
                        point.c_rate = None
                if cleared:
                    values = ", ".join(item.value for item in conflict.reported_values)
                    result.extraction_notes.append(
                        f"Guardrail: conflicted c_rate values ({values}) for {group.group_id} remain unresolved; "
                        "disputed point-level c_rate assignments were removed."
                    )
        if _qualitative_only(group.temperature) and group.temperature.value is not None:
            raw = group.temperature.raw_value
            group.temperature.value = None
            group.temperature.unit = None
            group.temperature.qualifier = "unknown"
            result.extraction_notes.append(
                f"Guardrail: removed unsupported numeric temperature inferred from qualitative source value '{raw}'."
            )
        for point in group.performance_points:
            # A bare Warburg coefficient number is dimensionally ambiguous. Preserve the reported raw value
            # for review, but do not let it enter canonical quantitative results until a unit is explicit.
            if (
                point.property == "warburg_coefficient"
                and point.value is not None
                and not (point.unit and point.unit.strip())
            ):
                raw = point.raw_value or str(point.value)
                point.value = None
                point.qualifier = "unknown"
                result.extraction_notes.append(
                    f"Guardrail: unitless warburg_coefficient '{raw}' for {group.group_id} was retained as raw "
                    "source text but excluded from canonical quantitative admission until its unit is explicit."
                )
            if point.c_rate:
                want = re.sub(r"\s+", "", point.c_rate.lower())
                snippets = [ev.text_snippet for ev in point.evidence if ev.text_snippet]
                if not snippets or not any(want in re.sub(r"\s+", "", snippet.lower()) for snippet in snippets):
                    result.extraction_notes.append(
                        f"Association warning: c_rate '{point.c_rate}' for {group.group_id}/{point.property} "
                        "is not stated in the attached evidence snippet; review before curation."
                    )

    # De-duplicate notes while preserving order.
    result.extraction_notes = list(dict.fromkeys(result.extraction_notes))
    return result
