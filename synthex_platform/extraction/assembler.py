from __future__ import annotations

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import stable_id, source_id
from synthex_platform.core.models import (
    CalculationRecord, DeviceEntity, DomainPayload, ExperimentRecord, MaterialEntity,
    ProcessStep, Relationship, SourceRecord
)
from synthex_platform.core.quality import score_archive
from .draft_models import ExtractedDocument
from .additive_manufacturing_contract import additive_manufacturing_admission_decision
from .mechanical_contract import mechanical_admission_decision
from .photovoltaics_contract import (
    photovoltaics_admission_decision,
    photovoltaics_device_decision,
)
from .thermoelectrics_contract import thermoelectrics_admission_decision
from .membranes_contract import (
    membranes_admission_decision,
    membranes_device_decision,
)
from .semiconductors_contract import (
    semiconductor_admission_decision,
    semiconductor_device_decision,
)
from .biomaterials_contract import biomaterials_admission_decision, biomaterials_device_decision


class _GenericAdmissibilityGate:
    """Keep non-focal generic extraction objects auditable without making them canonical."""

    def __init__(self, domain: str):
        self.domain = domain
        self.quarantine: list[dict] = []

    def admit(self, kind: str, item) -> bool:
        ownership = item.ownership
        evidence = list(item.evidence)
        if ownership != "focal_work":
            reason = f"ownership_{ownership}"
        elif not any(evidence_item.text_snippet and (
            self.domain not in {"mechanical", "additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"}
            or evidence_item.verbatim_match is True
        ) for evidence_item in evidence):
            reason = "no_source_evidence"
        else:
            return True
        self.quarantine.append({
            "kind": kind, "local_id": item.local_id, "ownership": ownership,
            "reason": reason, "raw_object": item.model_dump(mode="json", exclude_none=True),
        })
        return False


def assemble_archive(draft: ExtractedDocument, domain: str, model: str | None = None) -> SynthexArchive:
    sid = source_id(draft.source.doi, draft.source.title)
    archive_id = stable_id("arc", sid, domain)
    local_map: dict[str, str] = {}
    gate = _GenericAdmissibilityGate(domain)

    materials = []
    for item in draft.materials:
        if not gate.admit("material", item):
            continue
        mid = stable_id("mat", sid, item.local_id, item.formula or "", item.name or "")
        local_map[item.local_id] = mid
        materials.append(MaterialEntity(
            material_id=mid, name=item.name, formula=item.formula, composition=item.composition,
            elements=item.elements, phase=item.phase, morphology=item.morphology,
            defects=item.defects, dopants=item.dopants, tags=item.tags, evidence=item.evidence,
        ))

    relationships = []
    devices = []
    for item in draft.devices:
        if not gate.admit("device", item):
            continue
        if domain == "photovoltaics":
            decision = photovoltaics_device_decision(item)
            if not decision.admitted:
                gate.quarantine.append({
                    "kind": "device", "local_id": item.local_id,
                    "ownership": item.ownership, "reason": decision.reason,
                    "raw_object": item.model_dump(mode="json", exclude_none=True),
                })
                continue
        if domain == "membranes":
            decision = membranes_device_decision(item)
            if not decision.admitted:
                gate.quarantine.append({
                    "kind": "device", "local_id": item.local_id,
                    "ownership": item.ownership, "reason": decision.reason,
                    "raw_object": item.model_dump(mode="json", exclude_none=True),
                })
                continue
        if domain == "semiconductors":
            decision = semiconductor_device_decision(item)
            if not decision.admitted:
                gate.quarantine.append({
                    "kind": "device", "local_id": item.local_id,
                    "ownership": item.ownership, "reason": decision.reason,
                    "raw_object": item.model_dump(mode="json", exclude_none=True),
                })
                continue
        if domain == "biomaterials":
            decision = biomaterials_device_decision(item)
            if not decision.admitted:
                gate.quarantine.append({
                    "kind": "device", "local_id": item.local_id,
                    "ownership": item.ownership, "reason": decision.reason,
                    "raw_object": item.model_dump(mode="json", exclude_none=True),
                })
                continue
        ordered_layers = sorted(item.layer_stack, key=lambda layer: layer.sequence_index)
        missing_refs = [layer.material_ref for layer in ordered_layers if layer.material_ref not in local_map]
        if missing_refs:
            gate.quarantine.append({
                "kind": "device", "local_id": item.local_id,
                "ownership": item.ownership,
                "reason": "layer_material_dependencies_not_admitted",
                "missing_material_refs": sorted(set(missing_refs)),
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        did = stable_id("dev", sid, item.local_id, item.device_type, item.name or "")
        local_map[item.local_id] = did
        layer_stack = []
        for layer in ordered_layers:
            material_id = local_map[layer.material_ref]
            layer_data = {
                "sequence_index": layer.sequence_index,
                "role": layer.role,
                "material_id": material_id,
            }
            if layer.thickness is not None:
                layer_data["thickness"] = layer.thickness.model_dump(mode="json", exclude_none=True)
            if layer.deposition_method is not None:
                layer_data["deposition_method"] = layer.deposition_method
            if layer.evidence:
                layer_data["evidence"] = [
                    evidence.model_dump(mode="json", exclude_none=True)
                    for evidence in layer.evidence
                ]
            layer_stack.append(layer_data)
            relationships.append(Relationship(
                relation_id=stable_id("rel", material_id, "layer_of", did, layer.sequence_index),
                subject_id=material_id,
                predicate="layer_of",
                object_id=did,
                attributes={"role": layer.role, "sequence_index": layer.sequence_index},
                evidence=layer.evidence or item.evidence,
            ))
        configuration = {**item.configuration, "layer_stack": layer_stack}
        devices.append(DeviceEntity(
            device_id=did,
            name=item.name,
            device_type=item.device_type,
            material_ids=[local_map[layer.material_ref] for layer in ordered_layers],
            configuration=configuration,
            tags=item.tags,
            evidence=item.evidence,
        ))

    processes = []
    experiments = []
    calculations = []

    def admitted_outputs(kind: str, local_id: str, outputs, modality: str):
        if domain not in {"mechanical", "additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"}:
            return list(outputs)
        admitted = []
        for output in outputs:
            decision = biomaterials_admission_decision(output, role="result", modality=modality) if domain == "biomaterials" else semiconductor_admission_decision(output, role="result", modality=modality) if domain == "semiconductors" else (
                mechanical_admission_decision(output, modality=modality)
                if domain == "mechanical"
                else additive_manufacturing_admission_decision(
                    output, role="result", modality=modality
                )
                if domain == "additive_manufacturing"
                else photovoltaics_admission_decision(
                    output, role="result", modality=modality
                )
                if domain == "photovoltaics"
                else thermoelectrics_admission_decision(
                    output, role="result", modality=modality
                )
                if domain == "thermoelectrics"
                else membranes_admission_decision(
                    output, role="result",
                    modality=str(output.conditions.get("membrane_modality") or ""),
                )
            )
            if decision.admitted:
                admitted.append(output)
                continue
            gate.quarantine.append({
                "kind": "measurement",
                "record_kind": kind,
                "local_id": local_id,
                "property": output.property,
                "reason": decision.reason,
                "raw_object": output.model_dump(mode="json", exclude_none=True),
            })
        return admitted

    def admitted_process_parameters(local_id: str, parameters):
        if domain not in {"additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"}:
            return list(parameters)
        admitted = []
        for parameter in parameters:
            decision = biomaterials_admission_decision(parameter, role="process_parameter") if domain == "biomaterials" else semiconductor_admission_decision(parameter, role="process_parameter") if domain == "semiconductors" else (
                additive_manufacturing_admission_decision(parameter, role="process_parameter")
                if domain == "additive_manufacturing"
                else photovoltaics_admission_decision(parameter, role="process_parameter")
                if domain == "photovoltaics"
                else thermoelectrics_admission_decision(parameter, role="process_parameter")
                if domain == "thermoelectrics"
                else membranes_admission_decision(
                    parameter, role="process_parameter", modality="fabrication"
                )
            )
            if decision.admitted:
                admitted.append(parameter)
                continue
            gate.quarantine.append({
                "kind": "measurement", "record_kind": "process",
                "local_id": local_id, "property": parameter.property,
                "reason": decision.reason,
                "raw_object": parameter.model_dump(mode="json", exclude_none=True),
            })
        return admitted

    for i, item in enumerate(draft.processes):
        if not gate.admit("process", item):
            continue
        pid = stable_id("proc", sid, item.local_id, item.name)
        local_map[item.local_id] = pid
        input_local_refs = item.input_material_refs or item.material_refs
        output_local_refs = item.output_material_refs or item.material_refs
        inputs = [local_map[r] for r in input_local_refs if r in local_map]
        outputs = [local_map[r] for r in output_local_refs if r in local_map]
        input_device_refs = [local_map[r] for r in item.input_device_refs if r in local_map]
        output_device_refs = [local_map[r] for r in item.output_device_refs if r in local_map]
        if (
            (input_local_refs and len(inputs) != len(input_local_refs))
            or (output_local_refs and len(outputs) != len(output_local_refs))
            or (item.input_device_refs and len(input_device_refs) != len(item.input_device_refs))
            or (item.output_device_refs and len(output_device_refs) != len(item.output_device_refs))
        ):
            gate.quarantine.append({"kind": "process", "local_id": item.local_id, "ownership": item.ownership, "reason": "entity_dependencies_not_admitted", "raw_object": item.model_dump(mode="json", exclude_none=True)})
            continue
        parameters = admitted_process_parameters(item.local_id, item.parameters)
        if domain in {"additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"} and item.parameters and not parameters:
            gate.quarantine.append({
                "kind": "process", "local_id": item.local_id, "ownership": item.ownership,
                "reason": f"no_admitted_{domain}_process_parameters",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        processes.append(ProcessStep(
            process_id=pid, name=item.name, family=item.family, sequence_index=i,
            inputs=[*inputs, *input_device_refs], outputs=[*outputs, *output_device_refs], parameters=parameters, atmosphere=item.atmosphere,
            equipment=item.equipment, evidence=item.evidence,
        ))
        explicit_lineage = bool(
            domain == "additive_manufacturing"
            or item.input_material_refs or item.output_material_refs
        )
        if explicit_lineage:
            for mid in inputs:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", mid, "input_to", pid),
                    subject_id=mid, predicate="input_to", object_id=pid,
                ))
        for mid in outputs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "processed_by", pid),
                subject_id=mid, predicate="processed_by", object_id=pid,
            ))
            if explicit_lineage:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", pid, "produces", mid),
                    subject_id=pid, predicate="produces", object_id=mid,
                ))
        for did in input_device_refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", did, "input_to", pid),
                subject_id=did, predicate="input_to", object_id=pid,
            ))
        for did in output_device_refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", pid, "produces", did),
                subject_id=pid, predicate="produces", object_id=did,
            ))

    for item in draft.experiments:
        if not gate.admit("experiment", item):
            continue
        if domain in {"mechanical", "additive_manufacturing", "thermoelectrics"} and (
            len(item.material_refs) != 1 or item.material_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id, "ownership": item.ownership,
                "reason": "ambiguous_or_missing_material_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        if domain == "photovoltaics" and (
            len(item.device_refs) != 1 or item.device_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id,
                "ownership": item.ownership,
                "reason": "ambiguous_or_missing_device_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        if domain == "membranes" and (
            len(item.device_refs) != 1 or item.device_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id,
                "ownership": item.ownership,
                "reason": "ambiguous_or_missing_membrane_specimen_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        if domain == "semiconductors" and (
            len(item.device_refs) != 1 or item.device_refs[0] not in local_map
            or len(item.material_refs) != 1 or item.material_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id,
                "ownership": item.ownership,
                "reason": "ambiguous_or_missing_semiconductor_specimen_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        if domain == "biomaterials" and (
            len(item.device_refs) != 1 or item.device_refs[0] not in local_map
            or len(item.material_refs) != 1 or item.material_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id,
                "ownership": item.ownership,
                "reason": "ambiguous_or_missing_biomaterial_specimen_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        outputs = admitted_outputs("experiment", item.local_id, item.outputs, "experimental")
        if domain in {"mechanical", "additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"} and not outputs:
            gate.quarantine.append({
                "kind": "experiment", "local_id": item.local_id, "ownership": item.ownership,
                "reason": f"no_admitted_{domain}_outputs",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        eid = stable_id("exp", sid, item.local_id, item.experiment_type)
        local_map[item.local_id] = eid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
        device_refs = [local_map[r] for r in item.device_refs if r in local_map]
        if item.material_refs and not refs:
            gate.quarantine.append({"kind": "experiment", "local_id": item.local_id, "ownership": item.ownership, "reason": "material_dependencies_not_admitted", "raw_object": item.model_dump(mode="json", exclude_none=True)})
            continue
        experiments.append(ExperimentRecord(
            experiment_id=eid, experiment_type=item.experiment_type, material_ids=refs,
            device_id=device_refs[0] if len(device_refs) == 1 else None,
            device_ids=device_refs,
            target=item.target, conditions=item.conditions, outputs=outputs,
            protocol=item.protocol, evidence=item.evidence,
        ))
        for mid in refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "tested_in", eid),
                subject_id=mid, predicate="tested_in", object_id=eid,
            ))
        for did in device_refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", did, "tested_in", eid),
                subject_id=did, predicate="tested_in", object_id=eid,
            ))

    for item in draft.calculations:
        if not gate.admit("calculation", item):
            continue
        if domain in {"mechanical", "additive_manufacturing", "thermoelectrics", "membranes", "semiconductors", "biomaterials"} and (
            len(item.material_refs) != 1 or item.material_refs[0] not in local_map
        ):
            gate.quarantine.append({
                "kind": "calculation", "local_id": item.local_id, "ownership": item.ownership,
                "reason": "ambiguous_or_missing_material_association",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        outputs = admitted_outputs("calculation", item.local_id, item.outputs, "computational")
        if domain in {"mechanical", "additive_manufacturing", "photovoltaics", "thermoelectrics", "membranes", "semiconductors", "biomaterials"} and not outputs:
            gate.quarantine.append({
                "kind": "calculation", "local_id": item.local_id, "ownership": item.ownership,
                "reason": f"no_admitted_{domain}_outputs",
                "raw_object": item.model_dump(mode="json", exclude_none=True),
            })
            continue
        cid = stable_id("calc", sid, item.local_id, item.calculation_type)
        local_map[item.local_id] = cid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
        if item.material_refs and not refs:
            gate.quarantine.append({"kind": "calculation", "local_id": item.local_id, "ownership": item.ownership, "reason": "material_dependencies_not_admitted", "raw_object": item.model_dump(mode="json", exclude_none=True)})
            continue
        calculations.append(CalculationRecord(
            calculation_id=cid, calculation_type=item.calculation_type, material_ids=refs,
            code=item.code, method=item.method, functional=item.functional, model=item.model,
            parameters=item.parameters, outputs=outputs, evidence=item.evidence,
        ))
        for mid in refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", cid, "calculated_for", mid),
                subject_id=cid, predicate="calculated_for", object_id=mid,
            ))

    source = SourceRecord(
        source_id=sid, title=draft.source.title, doi=draft.source.doi, url=draft.source.url,
        year=draft.source.year, authors=draft.source.authors,
    )
    relationships.append(Relationship(
        relation_id=stable_id("rel", archive_id, "reported_by", sid),
        subject_id=archive_id, predicate="reported_by", object_id=sid,
    ))
    archive = SynthexArchive(
        metadata=ArchiveMetadata(archive_id=archive_id, domain=domain, extractor_model=model),
        sources=[source], materials=materials, devices=devices, processes=processes, experiments=experiments,
        calculations=calculations, relationships=relationships,
        domain_payloads=[DomainPayload(domain=domain, schema_version="1.0.0", values={
            **draft.domain_values,
            "admissibility": {
                "policy": (
                    "mechanical_focal_evidence_property_unit_series_v1"
                    if domain == "mechanical"
                    else "am_process_result_focal_verbatim_unit_family_v1"
                    if domain == "additive_manufacturing"
                    else "photovoltaics_device_linked_focal_verbatim_context_v1"
                    if domain == "photovoltaics"
                    else "thermoelectrics_material_linked_sign_orientation_derivation_v1"
                    if domain == "thermoelectrics"
                    else "membranes_specimen_linked_modality_condition_table_evidence_v1"
                    if domain == "membranes"
                    else "semiconductors_film_wafer_device_property_method_unit_evidence_v1"
                    if domain == "semiconductors"
                    else "biomaterials_specimen_assay_time_property_unit_evidence_v1"
                    if domain == "biomaterials"
                    else "generic_focal_work_with_source_evidence_v1"
                ),
                "quarantined_objects": gate.quarantine,
            },
        })],
    )
    return score_archive(archive)
