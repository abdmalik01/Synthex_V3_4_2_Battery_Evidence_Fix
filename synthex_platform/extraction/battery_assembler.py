from __future__ import annotations

from typing import Iterable

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import stable_id, source_id
from synthex_platform.core.models import (
    CalculationRecord, DeviceEntity, Evidence, ExperimentRecord, MaterialEntity, Measurement, ProcessStep,
    Relationship, SourceRecord, DomainPayload, SourceType,
)
from synthex_platform.core.quality import score_archive
from .battery_models import (
    BatteryDocument, BatteryEvidence, BatteryQuantity, SharedBatteryProtocol,
    ChargeProtocol, DischargeProtocol, ImpedanceProtocol, ElectrochemicalTesting,
    ElectrodeFabrication, CellAssembly,
)
from .battery_evidence import verify_battery_evidence
from .battery_normalizer import normalize_battery_quantity


NON_FOCAL_OWNERSHIP = {
    "cited_prior_work", "review_summary", "comparison_table", "background",
}

COMPUTATIONAL_PROPERTIES = {
    "formation_energy", "insertion_voltage", "intercalation_voltage", "reaction_voltage",
    "migration_barrier", "migration_energy_barrier", "diffusion_barrier", "binding_energy",
    "adsorption_energy", "band_gap", "density_of_states", "dos", "defect_energy",
    "defect_formation_energy", "electronic_structure",
}


class _AdmissibilityGate:
    def __init__(self):
        self.admitted = 0
        self.quarantine: list[dict] = []

    def admit(self, *, path: str, property_name: str, raw_value, value, unit,
              ownership: str, evidence: Iterable[BatteryEvidence]) -> bool:
        evidence_items = list(evidence)
        if ownership != "focal_work":
            reason = f"ownership_{ownership}"
        elif not any(item.verbatim_match is True for item in evidence_items):
            reason = "no_verbatim_evidence"
        else:
            self.admitted += 1
            return True
        self.quarantine.append({
            "path": path,
            "property": property_name,
            "raw_value": raw_value,
            "value": value,
            "unit": unit,
            "ownership": ownership,
            "reason": reason,
            "evidence": [item.model_dump(exclude_none=True) for item in evidence_items],
        })
        return False

    def payload(self) -> dict:
        return {
            "policy": "focal_work_with_normalized_verbatim_evidence_v1",
            "admitted_quantitative_values": self.admitted,
            "quarantined_quantitative_values": len(self.quarantine),
            "quarantine": self.quarantine,
        }


def _effective_ownership(group_ownership: str, item_ownership: str = "unknown") -> str:
    if group_ownership in NON_FOCAL_OWNERSHIP:
        return group_ownership
    if item_ownership != "unknown":
        return item_ownership
    return group_ownership


def _is_computational_point(point, paper_types: set[str]) -> bool:
    method = (point.method or "").lower()
    return (
        point.property in COMPUTATIONAL_PROPERTIES
        and ("computational_dft" in paper_types or "dft" in method or "first-principles" in method)
    )


def _ev_one(ev: BatteryEvidence | None, sid: str) -> Evidence | None:
    if ev is None:
        return None
    try:
        st = SourceType(ev.source_type)
    except Exception:
        st = SourceType.unknown
    return Evidence(
        source_id=sid, page=ev.page, section=ev.section, source_type=st,
        original_source_type=ev.original_source_type,
        verbatim_match=ev.verbatim_match,
        text_snippet=ev.text_snippet, confidence=ev.confidence,
    )


def _ev_many(evidence: Iterable[BatteryEvidence], sid: str) -> list[Evidence]:
    out = []
    for ev in evidence:
        x = _ev_one(ev, sid)
        if x is not None:
            out.append(x)
    return out


def _measurement(property_name: str, q: BatteryQuantity | None, sid: str,
                 evidence: BatteryEvidence | Iterable[BatteryEvidence] | None = None, *,
                 gate: _AdmissibilityGate, audit_path: str, ownership: str, **conditions):
    if q is None:
        return None
    nv, nu = normalize_battery_quantity(q)
    evidence_items = (
        [] if evidence is None
        else [evidence] if isinstance(evidence, BatteryEvidence)
        else list(evidence)
    )
    if q.value is not None and not gate.admit(
        path=audit_path,
        property_name=property_name,
        raw_value=q.raw_value,
        value=q.value,
        unit=q.unit,
        ownership=ownership,
        evidence=evidence_items,
    ):
        return None
    return Measurement(
        property=property_name,
        raw_value=q.raw_value,
        value=q.value,
        unit=q.unit,
        normalized_value=nv,
        normalized_unit=nu,
        qualifier=q.qualifier,
        conditions={k: v for k, v in conditions.items() if v is not None},
        evidence=_ev_many(evidence_items, sid),
    )


def _resolved_protocol(doc: BatteryDocument, group):
    charge = group.charge_protocol
    discharge = group.discharge_protocol
    eis = group.impedance_protocol
    ect = group.electrochemical_testing
    electrode = group.electrode_fabrication
    cell = group.cell_assembly
    lookup = {p.protocol_id: p for p in doc.shared_protocols}
    for ref in group.protocol_refs:
        p = lookup.get(ref)
        if not p:
            continue
        charge = charge or p.charge_protocol
        discharge = discharge or p.discharge_protocol
        eis = eis or p.impedance_protocol
        ect = ect or p.electrochemical_testing
        electrode = electrode or p.electrode_fabrication
        cell = cell or p.cell_assembly
    return charge, discharge, eis, ect, electrode, cell


def _battery_completeness(doc: BatteryDocument) -> float:
    checks: list[bool] = [bool(doc.source.title), bool(doc.battery_groups)]
    groups = doc.battery_groups
    types = set(doc.paper_types)

    if "battery_dataset_modelling" in types or "degradation_health" in types:
        checks += [
            any(g.battery_ids for g in groups),
            any(g.temperature for g in groups),
            any(g.measured_variables for g in groups),
        ]
    if "materials_synthesis" in types:
        checks += [
            bool(doc.materials),
            any(m.synthesis and m.synthesis.method for m in doc.materials),
            any(m.synthesis and (m.synthesis.steps or m.synthesis.calcination_temperatures) for m in doc.materials),
        ]
    if "electrode_fabrication" in types:
        checks.append(any((g.electrode_fabrication or any(
            p.electrode_fabrication for p in doc.shared_protocols if p.protocol_id in g.protocol_refs
        )) for g in groups))
    if "cell_assembly" in types:
        checks.append(any((g.cell_assembly or any(
            p.cell_assembly for p in doc.shared_protocols if p.protocol_id in g.protocol_refs
        )) for g in groups))
    if "electrochemical_performance" in types:
        checks += [
            any(g.performance_points for g in groups),
            any((g.electrochemical_testing or any(
                p.electrochemical_testing for p in doc.shared_protocols if p.protocol_id in g.protocol_refs
            )) for g in groups),
        ]
    if "impedance_eis" in types:
        checks.append(any((_resolved_protocol(doc, g)[2] is not None) for g in groups))
    return sum(checks) / max(len(checks), 1)


def assemble_battery_archive(
    doc: BatteryDocument,
    model: str | None = None,
    source_text: str | None = None,
) -> SynthexArchive:
    source_text = source_text if source_text is not None else doc._source_text
    if source_text:
        verify_battery_evidence(doc, source_text)
    gate = _AdmissibilityGate()
    reference_warnings: list[str] = []
    valid_material_refs = {material.material_id for material in doc.materials}
    valid_protocol_refs = {protocol.protocol_id for protocol in doc.shared_protocols}

    sid = source_id(doc.source.doi, doc.source.title)
    archive_id = stable_id("arc", sid, "batteries")
    source = SourceRecord(
        source_id=sid, source_type="paper", title=doc.source.title, doi=doc.source.doi,
        url=doc.source.url, year=doc.source.year, authors=doc.source.authors,
    )

    relationships: list[Relationship] = [Relationship(
        relation_id=stable_id("rel", archive_id, "reported_by", sid),
        subject_id=archive_id, predicate="reported_by", object_id=sid,
    )]
    materials: list[MaterialEntity] = []
    processes: list[ProcessStep] = []
    material_map: dict[str, str] = {}

    for material in doc.materials:
        mid = stable_id("mat", sid, material.material_id)
        material_map[material.material_id] = mid
        materials.append(MaterialEntity(
            material_id=mid, name=material.name or material.formula, formula=material.formula,
            structure={"phase": material.phase} if material.phase else {},
            morphology={"description": material.morphology} if material.morphology else {},
            tags=[material.role, "battery_material", f"ownership:{material.ownership}"],
            evidence=_ev_many(material.evidence, sid),
        ))
        if material.synthesis:
            syn = material.synthesis
            if syn.steps:
                for idx, step in enumerate(syn.steps):
                    pid = stable_id("proc", sid, material.material_id, step.step, idx)
                    params = []
                    step_evidence = step.evidence or ([] if not syn.evidence else [syn.evidence[0]])
                    for prop, q in [("temperature", step.temperature), ("duration", step.duration)]:
                        m = _measurement(
                            prop, q, sid, step_evidence, gate=gate,
                            audit_path=f"materials[{material.material_id}].synthesis.steps[{idx}].{prop}",
                            ownership=material.ownership,
                        )
                        if m:
                            params.append(m)
                    if material.ownership == "focal_work":
                        processes.append(ProcessStep(
                            process_id=pid, name=step.step, family=syn.method,
                            sequence_index=idx, inputs=syn.precursors if idx == 0 else [], outputs=[mid] if idx == len(syn.steps)-1 else [],
                            parameters=params, atmosphere=step.atmosphere or syn.atmosphere,
                            evidence=_ev_many(step_evidence, sid),
                        ))
                        relationships.append(Relationship(
                            relation_id=stable_id("rel", mid, "processed_by", pid), subject_id=mid,
                            predicate="processed_by", object_id=pid,
                        ))
            else:
                pid = stable_id("proc", sid, material.material_id, syn.method or "synthesis")
                params = [
                    _measurement(
                        "calcination_temperature", q, sid, syn.evidence, gate=gate,
                        audit_path=f"materials[{material.material_id}].synthesis.calcination_temperatures[{idx}]",
                        ownership=material.ownership,
                    )
                    for idx, q in enumerate(syn.calcination_temperatures)
                ]
                if material.ownership == "focal_work":
                    processes.append(ProcessStep(
                        process_id=pid, name=syn.method or "battery material synthesis", family=syn.method,
                        inputs=syn.precursors, outputs=[mid], parameters=[x for x in params if x],
                        atmosphere=syn.atmosphere, evidence=_ev_many(syn.evidence, sid),
                    ))
                    relationships.append(Relationship(
                        relation_id=stable_id("rel", mid, "processed_by", pid), subject_id=mid,
                        predicate="processed_by", object_id=pid,
                    ))

    devices: list[DeviceEntity] = []
    experiments: list[ExperimentRecord] = []
    calculations: list[CalculationRecord] = []

    for group in doc.battery_groups:
        charge, discharge, eis, ect, electrode, cell = _resolved_protocol(doc, group)
        if group.material_ref and group.material_ref not in valid_material_refs:
            reference_warnings.append(
                f"Battery group '{group.group_id}' has unknown material_ref '{group.material_ref}'; "
                "the reference was omitted from canonical entities."
            )
        invalid_protocol_refs = [ref for ref in group.protocol_refs if ref not in valid_protocol_refs]
        for ref in invalid_protocol_refs:
            reference_warnings.append(
                f"Battery group '{group.group_id}' has unknown protocol_ref '{ref}'; "
                "the reference was omitted from canonical entities."
            )
        canonical_protocol_refs = [ref for ref in group.protocol_refs if ref in valid_protocol_refs]
        point_ownerships = [
            _effective_ownership(group.ownership, point.ownership)
            for point in group.performance_points
        ]
        group_is_focal = group.ownership == "focal_work" or "focal_work" in point_ownerships
        material_id = material_map.get(group.material_ref or "")
        device_ids: list[str] = []
        ids = group.battery_ids or [group.group_id]
        for battery_id in ids if group_is_focal else []:
            did = stable_id("dev", sid, battery_id)
            device_ids.append(did)
            configuration = {
                "chemistry": group.chemistry,
                "cathode": group.cathode,
                "anode": group.anode,
                "electrolyte": group.electrolyte,
                "cell_format": group.cell_format or (cell.cell_format if cell else None),
                "source_group": group.group_id,
                "variant_label": group.variant_label,
                "protocol_refs": canonical_protocol_refs or None,
            }
            if cell:
                configuration.update({
                    "counter_electrode": cell.counter_electrode,
                    "reference_electrode": cell.reference_electrode,
                    "separator": cell.separator,
                    "cell_electrolyte": cell.electrolyte,
                    "assembly_atmosphere": cell.atmosphere,
                })
            devices.append(DeviceEntity(
                device_id=did, name=battery_id, device_type="battery_cell",
                material_ids=[material_id] if material_id else [],
                configuration={k: v for k, v in configuration.items() if v is not None},
                tags=["battery", f"ownership:{group.ownership}"], evidence=_ev_many(group.evidence, sid),
            ))
            if material_id:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", did, "contains_material", material_id),
                    subject_id=did, predicate="contains_material", object_id=material_id,
                ))

        # Electrode fabrication becomes a process connected to the material/device.
        if electrode and group_is_focal:
            proc_id = stable_id("proc", sid, group.group_id, "electrode_fabrication")
            params = []
            for prop, q in [
                ("active_material_fraction", electrode.active_material_fraction),
                ("conductive_fraction", electrode.conductive_fraction),
                ("binder_fraction", electrode.binder_fraction),
                ("mass_loading", electrode.mass_loading),
                ("pressing_pressure", electrode.pressing_pressure),
                ("disk_diameter", electrode.disk_diameter),
            ]:
                m = _measurement(
                    prop, q, sid, electrode.evidence or group.evidence, gate=gate,
                    audit_path=f"battery_groups[{group.group_id}].electrode_fabrication.{prop}",
                    ownership=group.ownership,
                )
                if m: params.append(m)
            processes.append(ProcessStep(
                process_id=proc_id, name="electrode fabrication", family=electrode.coating_method,
                inputs=[x for x in [electrode.active_material, electrode.conductive_additive, electrode.binder, electrode.solvent] if x],
                outputs=device_ids, parameters=params, equipment=electrode.current_collector,
                evidence=_ev_many(electrode.evidence or group.evidence[:1], sid),
            ))
            for did in device_ids:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", did, "processed_by", proc_id), subject_id=did,
                    predicate="processed_by", object_id=proc_id,
                ))

        conditions: list[Measurement] = []
        for prop, q in [
            ("temperature", group.temperature),
            ("calcination_temperature", group.calcination_temperature),
        ]:
            m = _measurement(
                prop, q, sid, group.evidence, gate=gate,
                audit_path=f"battery_groups[{group.group_id}].{prop}",
                ownership=group.ownership,
            )
            if m: conditions.append(m)
        if charge:
            for prop, q in [
                ("charge_current", charge.constant_current),
                ("charge_voltage_limit", charge.voltage_limit),
                ("charge_cutoff_current", charge.cutoff_current),
            ]:
                m = _measurement(
                    prop, q, sid, group.evidence, gate=gate,
                    audit_path=f"battery_groups[{group.group_id}].charge_protocol.{prop}",
                    ownership=group.ownership, protocol=charge.mode,
                )
                if m: conditions.append(m)
        if discharge:
            m = _measurement(
                "discharge_current", discharge.current, sid, group.evidence, gate=gate,
                audit_path=f"battery_groups[{group.group_id}].discharge_protocol.current",
                ownership=group.ownership, protocol=discharge.mode,
            )
            if m: conditions.append(m)
            cutoff_values = ([discharge.cutoff_voltage] if discharge.cutoff_voltage else []) + list(discharge.cutoff_voltages)
            for index, q in enumerate(cutoff_values):
                m = _measurement(
                    "discharge_cutoff_voltage", q, sid, group.evidence, gate=gate,
                    audit_path=f"battery_groups[{group.group_id}].discharge_protocol.cutoff_voltages[{index}]",
                    ownership=group.ownership,
                )
                if m: conditions.append(m)
        if ect:
            for prop, q in [
                ("cv_scan_rate", ect.cv_scan_rate), ("voltage_min", ect.voltage_min),
                ("voltage_max", ect.voltage_max), ("test_temperature", ect.temperature),
            ]:
                m = _measurement(
                    prop, q, sid, ect.evidence or group.evidence, gate=gate,
                    audit_path=f"battery_groups[{group.group_id}].electrochemical_testing.{prop}",
                    ownership=group.ownership,
                )
                if m: conditions.append(m)
            if ect.c_rate_definition and group_is_focal and any(
                item.verbatim_match is True for item in (ect.evidence or group.evidence)
            ):
                conditions.append(Measurement(property="c_rate_definition", raw_value=ect.c_rate_definition,
                                              value=ect.c_rate_definition, qualifier="categorical",
                                              evidence=_ev_many(ect.evidence or group.evidence, sid)))

        outputs: list[Measurement] = []
        calculation_outputs: list[Measurement] = []
        calculation_methods: list[str] = []
        for point_index, point in enumerate(group.performance_points):
            if point.value is None:
                continue
            ownership = _effective_ownership(group.ownership, point.ownership)
            if not gate.admit(
                path=f"battery_groups[{group.group_id}].performance_points[{point_index}]",
                property_name=point.property,
                raw_value=point.raw_value,
                value=point.value,
                unit=point.unit,
                ownership=ownership,
                evidence=point.evidence,
            ):
                continue
            q = BatteryQuantity(
                raw_value=point.raw_value,
                value=point.value,
                unit=point.unit,
                qualifier=point.qualifier,
            )
            nv, nu = normalize_battery_quantity(q)
            measurement = Measurement(
                property=point.property, raw_value=point.raw_value, value=point.value, unit=point.unit,
                normalized_value=nv, normalized_unit=nu, qualifier=q.qualifier, method=point.method,
                conditions={k: v for k, v in {
                    "cycle": point.cycle, "C_rate": point.c_rate, "voltage_window": point.voltage_window,
                    "temperature": point.temperature.raw_value if point.temperature else None,
                    "variant": group.variant_label,
                    "calcination_temperature": group.calcination_temperature.raw_value if group.calcination_temperature else None,
                }.items() if v is not None},
                evidence=_ev_many(point.evidence, sid),
            )
            if _is_computational_point(point, set(doc.paper_types)):
                calculation_outputs.append(measurement)
                if point.method and point.method not in calculation_methods:
                    calculation_methods.append(point.method)
            else:
                outputs.append(measurement)

        impedance_properties = {
            "charge_transfer_resistance", "internal_resistance", "impedance",
            "diffusion_coefficient", "warburg_coefficient",
        }
        general_outputs = [
            output for output in outputs
            if not (eis and output.property in impedance_properties)
        ]

        exp_id = stable_id("exp", sid, group.group_id, "battery_performance")
        protocol_parts = []
        if charge and charge.mode: protocol_parts.append(f"charge: {charge.mode}")
        if discharge and discharge.mode: protocol_parts.append(f"discharge: {discharge.mode}")
        if ect and ect.rate_capability_range: protocol_parts.append(f"rate capability: {ect.rate_capability_range}")
        if group_is_focal and (general_outputs or conditions or protocol_parts):
            experiments.append(ExperimentRecord(
                experiment_id=exp_id, experiment_type="battery performance / cycling",
                material_ids=[material_id] if material_id else [], device_ids=device_ids,
                target="battery performance and degradation", conditions=conditions, outputs=general_outputs,
                protocol="; ".join(protocol_parts) or None,
                evidence=_ev_many(group.evidence, sid),
            ))
            for did in device_ids:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", did, "tested_in", exp_id), subject_id=did,
                    predicate="tested_in", object_id=exp_id,
                ))

        if group_is_focal and calculation_outputs:
            calculation_id = stable_id("calc", sid, group.group_id, "battery_dft")
            calculations.append(CalculationRecord(
                calculation_id=calculation_id,
                calculation_type="battery first-principles / DFT",
                material_ids=[material_id] if material_id else [],
                method="; ".join(calculation_methods) or "DFT / first-principles",
                model={
                    key: value for key, value in {
                        "chemistry": group.chemistry,
                        "variant": group.variant_label,
                        "source_group": group.group_id,
                    }.items() if value is not None
                },
                outputs=calculation_outputs,
                evidence=_ev_many(group.evidence, sid),
            ))
            if material_id:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", material_id, "calculated_by", calculation_id),
                    subject_id=material_id, predicate="calculated_by", object_id=calculation_id,
                ))

        if eis and group_is_focal:
            eis_conditions: list[Measurement] = []
            for prop, q in [("frequency_min", eis.frequency_min), ("frequency_max", eis.frequency_max),
                            ("ac_amplitude", eis.amplitude), ("bias", eis.bias)]:
                m = _measurement(
                    prop, q, sid, group.evidence, gate=gate,
                    audit_path=f"battery_groups[{group.group_id}].impedance_protocol.{prop}",
                    ownership=group.ownership,
                )
                if m: eis_conditions.append(m)
            eis_outputs = [x for x in outputs if x.property in impedance_properties]
            eis_id = stable_id("exp", sid, group.group_id, "eis")
            experiments.append(ExperimentRecord(
                experiment_id=eis_id, experiment_type=eis.method or "electrochemical impedance spectroscopy",
                material_ids=[material_id] if material_id else [], device_ids=device_ids,
                target="impedance / transport", conditions=eis_conditions, outputs=eis_outputs,
                evidence=_ev_many(group.evidence, sid),
            ))
            for did in device_ids:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", did, "tested_in", eis_id), subject_id=did,
                    predicate="tested_in", object_id=eis_id,
                ))

    payload = DomainPayload(
        domain="batteries", schema_version="1.2.0", tags=doc.paper_types,
        values={
            "dataset_source": doc.source.dataset_source,
            "paper_types": doc.paper_types,
            "materials": [m.model_dump(exclude_none=True) for m in doc.materials],
            "shared_protocols": [p.model_dump(exclude_none=True) for p in doc.shared_protocols],
            "battery_groups": [g.model_dump(exclude_none=True) for g in doc.battery_groups],
            "extraction_notes": doc.extraction_notes,
            "pdf_text_parser": doc.source.pdf_text_parser or doc._pdf_parser,
            "admissibility": gate.payload(),
        },
    )

    archive = SynthexArchive(
        metadata=ArchiveMetadata(archive_id=archive_id, domain="batteries", extractor_model=model),
        sources=[source], materials=materials, devices=devices, processes=processes,
        experiments=experiments, calculations=calculations,
        relationships=relationships, domain_payloads=[payload],
    )
    archive = score_archive(archive)
    archive.quality.completeness = _battery_completeness(doc)
    if "electrochemical_performance" in set(doc.paper_types) and not any(g.performance_points for g in doc.battery_groups):
        archive.quality.semantic_warnings.append("Electrochemical-performance paper has no extracted quantitative performance points.")
    if "materials_synthesis" in set(doc.paper_types) and not doc.materials:
        archive.quality.semantic_warnings.append("Materials-synthesis paper has no structured material/synthesis record.")
    archive.quality.semantic_warnings.extend(reference_warnings)
    if gate.quarantine:
        archive.quality.semantic_warnings.append(
            f"Scientific admissibility gate quarantined {len(gate.quarantine)} quantitative value(s); "
            "raw values remain in the batteries domain payload."
        )
    conflicts = [
        conflict for group in doc.battery_groups for conflict in group.condition_conflicts
        if conflict.status == "conflicted" and conflict.resolved_value is None
    ]
    if conflicts:
        archive.quality.semantic_warnings.append(
            f"{len(conflicts)} unresolved experimental-condition conflict(s) remain in the raw domain payload."
        )
    archive.quality.semantic_warnings = list(dict.fromkeys(archive.quality.semantic_warnings))
    return archive
