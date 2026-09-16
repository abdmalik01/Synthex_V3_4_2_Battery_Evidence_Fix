"""Conservative Corrosion V1 archive assembly.

The assembler admits only focal, source-tracked scientific records. Cited/review
content and metrics that fail the explicit admission contract remain visible in the
Corrosion domain payload quarantine rather than entering canonical archive records.
"""

from __future__ import annotations

from collections.abc import Iterable

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import source_id, stable_id
from synthex_platform.core.models import (
    CalculationRecord,
    DomainPayload,
    Evidence,
    ExperimentRecord,
    MaterialEntity,
    Measurement,
    ProcessStep,
    Relationship,
    SourceRecord,
    SourceType,
)
from synthex_platform.core.quality import score_archive

from .corrosion_admission import decide_corrosion_metric_admission
from .corrosion_models import CorrosionDocument, CorrosionEvidence, CorrosionQuantity
from .source_context import SourceBundle


def _canonical_evidence(items: Iterable[CorrosionEvidence], sid: str) -> list[Evidence]:
    converted: list[Evidence] = []
    for item in items:
        try:
            source_type = SourceType(item.source_type)
        except ValueError:
            source_type = SourceType.unknown
        converted.append(Evidence(
            source_id=item.source_id or sid,
            page=item.page,
            section=item.section,
            source_type=source_type,
            original_source_type=item.original_source_type,
            verbatim_match=item.verbatim_match,
            text_snippet=item.text_snippet,
            table_id=item.table_id,
            figure_id=item.figure_id,
            locator=item.locator,
        ))
    return converted


def _verified(items: Iterable[CorrosionEvidence]) -> bool:
    return any(
        item.verbatim_match is True
        and bool(item.text_snippet)
        and item.original_source_type not in {"figure_reported", "unknown"}
        for item in items
    )


def _measurement(property_name: str, quantity: CorrosionQuantity, *, method: str | None = None,
                 conditions: dict | None = None, evidence: Iterable[CorrosionEvidence] = (), sid: str) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=quantity.raw_value,
        value=quantity.value,
        unit=quantity.unit,
        qualifier=quantity.qualifier,
        method=method,
        conditions={key: value for key, value in (conditions or {}).items() if value is not None},
        evidence=_canonical_evidence(evidence, sid),
    )


def _quantity_condition(name: str, quantity: CorrosionQuantity | None, *, sid: str,
                        evidence: Iterable[CorrosionEvidence] = ()) -> Measurement | None:
    if quantity is None:
        return None
    return _measurement(name, quantity, evidence=evidence, sid=sid)


class _Audit:
    def __init__(self) -> None:
        self.admitted_metrics = 0
        self.quarantine: list[dict] = []

    def reject(self, path: str, reason: str, obj, *, ownership: str | None = None) -> None:
        self.quarantine.append({
            "path": path,
            "reason": reason,
            **({"ownership": ownership} if ownership else {}),
            "object": obj.model_dump(mode="json", exclude_none=True) if hasattr(obj, "model_dump") else obj,
        })

    def payload(self) -> dict:
        return {
            "policy": "corrosion_focal_value_specific_verified_v1",
            "admitted_quantitative_values": self.admitted_metrics,
            "quarantined_objects_or_values": len(self.quarantine),
            "quarantine": self.quarantine,
        }


def _conflict_for_experiment(document: CorrosionDocument, experiment_id: str) -> bool:
    # Stage 1 conflict objects do not yet carry a record_ref. Conservatively bind a
    # conflict to an experiment when its field explicitly names that experiment, or
    # when the document has only one experiment and the field is a condition name.
    for conflict in document.condition_conflicts:
        if conflict.resolved_value is not None:
            continue
        if experiment_id in conflict.field:
            return True
        if len(document.experiments) == 1:
            return True
    return False


def assemble_corrosion_archive(
    document: CorrosionDocument,
    *,
    model: str | None = None,
    source_bundle: SourceBundle | None = None,
) -> SynthexArchive:
    checksum = source_bundle.source.source_checksum if source_bundle else None
    sid = source_id(document.source.doi, document.source.title, checksum)
    archive_id = stable_id("arc", sid, "corrosion")
    audit = _Audit()

    source = SourceRecord(
        source_id=sid,
        title=document.source.title,
        doi=document.source.doi,
        url=document.source.url,
        year=document.source.year,
        authors=document.source.authors,
        checksum=checksum,
    )
    relationships: list[Relationship] = [Relationship(
        relation_id=stable_id("rel", archive_id, "reported_by", sid),
        subject_id=archive_id,
        predicate="reported_by",
        object_id=sid,
    )]

    candidate_material_ids = {
        item.local_id: stable_id("mat", sid, item.local_id) for item in document.materials
    }
    material_ids: dict[str, str] = {}
    materials: list[MaterialEntity] = []
    for item in document.materials:
        path = f"materials.{item.local_id}"
        if document.scope_status != "supported":
            audit.reject(path, "unsupported_scope", item, ownership=item.ownership)
            continue
        if item.ownership != "focal_work":
            audit.reject(path, f"ownership_{item.ownership}", item, ownership=item.ownership)
            continue
        if not _verified(item.evidence):
            audit.reject(path, "no_verified_record_evidence", item, ownership=item.ownership)
            continue
        mid = candidate_material_ids[item.local_id]
        material_ids[item.local_id] = mid
        materials.append(MaterialEntity(
            material_id=mid,
            name=item.canonical_name or item.reported_name or item.reported_formula,
            formula=item.reported_formula,
            structure={
                "material_class": item.material_class,
                "role": item.role,
                "composition_raw": item.composition_raw,
            },
            tags=["corrosion", f"role:{item.role}", f"ownership:{item.ownership}"],
            evidence=_canonical_evidence(item.evidence, sid),
        ))

    processes: list[ProcessStep] = []
    process_ids: dict[str, str] = {}
    for prep in document.surface_preparations:
        path = f"surface_preparations.{prep.preparation_id}"
        target = material_ids.get(prep.material_ref)
        if prep.ownership != "focal_work":
            audit.reject(path, f"ownership_{prep.ownership}", prep, ownership=prep.ownership)
            continue
        if not target or not _verified(prep.evidence):
            audit.reject(path, "unresolved_material_or_evidence", prep, ownership=prep.ownership)
            continue
        pid = stable_id("proc", sid, prep.preparation_id)
        process_ids[prep.preparation_id] = pid
        steps = [
            value for value in (
                prep.grinding, prep.polishing, prep.cleaning, prep.degreasing,
                prep.pickling, prep.heat_treatment, *prep.additional_steps,
            ) if value
        ]
        processes.append(ProcessStep(
            process_id=pid,
            name="Surface preparation",
            family="corrosion_surface_preparation",
            outputs=[target],
            parameters=[Measurement(property="reported_step", raw_value=step, value=step, qualifier="categorical") for step in steps],
            evidence=_canonical_evidence(prep.evidence, sid),
        ))
        relationships.append(Relationship(
            relation_id=stable_id("rel", target, "processed_by", pid),
            subject_id=target,
            predicate="processed_by",
            object_id=pid,
            evidence=_canonical_evidence(prep.evidence, sid),
        ))

    treatments_by_id = {item.treatment_id: item for item in document.treatments}
    treatment_process_ids: dict[str, str] = {}
    for treatment in document.treatments:
        path = f"treatments.{treatment.treatment_id}"
        if treatment.ownership != "focal_work":
            audit.reject(path, f"ownership_{treatment.ownership}", treatment, ownership=treatment.ownership)
            continue
        if not _verified(treatment.evidence):
            audit.reject(path, "no_verified_record_evidence", treatment, ownership=treatment.ownership)
            continue
        target_ref = treatment.material_ref or treatment.substrate_ref
        target = material_ids.get(target_ref or "")
        if target_ref and not target:
            audit.reject(path, "unresolved_treatment_material", treatment, ownership=treatment.ownership)
            continue
        pid = stable_id("proc", sid, treatment.treatment_id)
        treatment_process_ids[treatment.treatment_id] = pid
        parameters: list[Measurement] = []
        if treatment.concentration:
            parameters.append(_measurement("concentration", treatment.concentration, sid=sid, evidence=treatment.evidence))
        if treatment.thickness:
            parameters.append(_measurement("thickness", treatment.thickness, sid=sid, evidence=treatment.evidence))
        processes.append(ProcessStep(
            process_id=pid,
            name=treatment.reported_name or treatment.treatment_type,
            family=treatment.treatment_type,
            outputs=[target] if target else [],
            parameters=parameters,
            evidence=_canonical_evidence(treatment.evidence, sid),
        ))
        if target:
            relationships.append(Relationship(
                relation_id=stable_id("rel", target, "processed_by", pid),
                subject_id=target,
                predicate="processed_by",
                object_id=pid,
                evidence=_canonical_evidence(treatment.evidence, sid),
            ))

    environments = {item.environment_id: item for item in document.environments}
    experiments: list[ExperimentRecord] = []
    experiment_ids: dict[str, str] = {}
    for experiment in document.experiments:
        path = f"experiments.{experiment.experiment_id}"
        if document.scope_status != "supported":
            audit.reject(path, "unsupported_scope", experiment, ownership=experiment.ownership)
            continue
        if experiment.ownership != "focal_work":
            audit.reject(path, f"ownership_{experiment.ownership}", experiment, ownership=experiment.ownership)
            continue
        resolved_materials = [material_ids[ref] for ref in experiment.material_refs if ref in material_ids]
        if len(resolved_materials) != len(experiment.material_refs) or not resolved_materials:
            audit.reject(path, "unresolved_or_missing_canonical_material", experiment, ownership=experiment.ownership)
            continue
        if not _verified(experiment.evidence):
            audit.reject(path, "no_verified_record_evidence", experiment, ownership=experiment.ownership)
            continue

        environment = environments.get(experiment.environment_ref or "")
        conditions: list[Measurement] = []
        if environment is not None:
            for name, quantity in (
                ("chloride_concentration", environment.chloride_concentration),
                ("pH", environment.pH),
                ("temperature", environment.temperature),
                ("exposure_time", environment.exposure_time),
            ):
                converted = _quantity_condition(name, quantity, sid=sid, evidence=environment.evidence)
                if converted:
                    conditions.append(converted)
            for name, value in (
                ("medium", environment.medium),
                ("electrolyte", environment.electrolyte),
                ("atmosphere", environment.atmosphere),
                ("flow_or_agitation", environment.flow_or_agitation),
            ):
                if value:
                    conditions.append(Measurement(
                        property=name, raw_value=value, value=value, qualifier="categorical",
                        evidence=_canonical_evidence(environment.evidence, sid),
                    ))

        reference_electrode = None
        if experiment.polarization_conditions:
            pc = experiment.polarization_conditions
            reference_electrode = pc.reference_electrode
            for name, quantity in (
                ("exposed_area", pc.exposed_area), ("scan_rate", pc.scan_rate),
                ("start_potential", pc.start_potential), ("end_potential", pc.end_potential),
                ("open_circuit_stabilization", pc.open_circuit_stabilization),
            ):
                converted = _quantity_condition(name, quantity, sid=sid, evidence=pc.evidence)
                if converted:
                    conditions.append(converted)
            if pc.reference_electrode:
                conditions.append(Measurement(property="reference_electrode", raw_value=pc.reference_electrode,
                    value=pc.reference_electrode, qualifier="categorical", evidence=_canonical_evidence(pc.evidence, sid)))
            if pc.counter_electrode:
                conditions.append(Measurement(property="counter_electrode", raw_value=pc.counter_electrode,
                    value=pc.counter_electrode, qualifier="categorical", evidence=_canonical_evidence(pc.evidence, sid)))
        elif experiment.eis_conditions:
            ec = experiment.eis_conditions
            reference_electrode = ec.reference_electrode
            for name, quantity in (
                ("exposed_area", ec.exposed_area), ("frequency_min", ec.frequency_min),
                ("frequency_max", ec.frequency_max), ("perturbation_amplitude", ec.perturbation_amplitude),
                ("dc_bias", ec.dc_bias),
            ):
                converted = _quantity_condition(name, quantity, sid=sid, evidence=ec.evidence)
                if converted:
                    conditions.append(converted)
            if ec.reference_electrode:
                conditions.append(Measurement(property="reference_electrode", raw_value=ec.reference_electrode,
                    value=ec.reference_electrode, qualifier="categorical", evidence=_canonical_evidence(ec.evidence, sid)))
            if ec.equivalent_circuit:
                conditions.append(Measurement(property="equivalent_circuit", raw_value=ec.equivalent_circuit,
                    value=ec.equivalent_circuit, qualifier="categorical", evidence=_canonical_evidence(ec.evidence, sid)))

        linked_treatments = [
            treatments_by_id[ref]
            for ref in experiment.treatment_refs
            if ref in treatment_process_ids and ref in treatments_by_id
        ]
        for treatment in linked_treatments:
            label = treatment.reported_name or treatment.treatment_type
            if label:
                conditions.append(Measurement(
                    property="treatment",
                    raw_value=label,
                    value=label,
                    qualifier="categorical",
                    evidence=_canonical_evidence(treatment.evidence, sid),
                ))
            if treatment.concentration:
                converted = _quantity_condition(
                    "treatment_concentration",
                    treatment.concentration,
                    sid=sid,
                    evidence=treatment.evidence,
                )
                if converted:
                    conditions.append(converted)
            if treatment.treatment_type == "inhibitor":
                if label:
                    conditions.append(Measurement(
                        property="inhibitor",
                        raw_value=label,
                        value=label,
                        qualifier="categorical",
                        evidence=_canonical_evidence(treatment.evidence, sid),
                    ))
                if treatment.concentration:
                    converted = _quantity_condition(
                        "inhibitor_concentration",
                        treatment.concentration,
                        sid=sid,
                        evidence=treatment.evidence,
                    )
                    if converted:
                        conditions.append(converted)

        outputs: list[Measurement] = []
        unresolved_conflict = _conflict_for_experiment(document, experiment.experiment_id)
        treatment_present = bool(experiment.treatment_refs) and all(
            ref in treatment_process_ids for ref in experiment.treatment_refs
        )
        for index, metric in enumerate(experiment.metrics):
            decision = decide_corrosion_metric_admission(
                metric,
                scope_status=document.scope_status,
                experiment_type=experiment.experiment_type,
                reference_electrode=reference_electrode,
                treatment_present=treatment_present,
                unresolved_conflict=unresolved_conflict,
            )
            metric_path = f"{path}.metrics.{index}"
            if not decision.admitted:
                audit.reject(metric_path, decision.reason or "not_admitted", metric, ownership=metric.ownership)
                continue
            metric_conditions = {
                "normalization_basis": metric.normalization_basis,
                "reference_electrode": reference_electrode if metric.property.endswith("potential") else None,
                "environment_ref": experiment.environment_ref,
                "treatment_refs": experiment.treatment_refs or None,
            }
            outputs.append(_measurement(
                metric.property,
                metric.quantity,
                method=metric.method,
                conditions=metric_conditions,
                evidence=metric.evidence,
                sid=sid,
            ))
            audit.admitted_metrics += 1

        eid = stable_id("exp", sid, experiment.experiment_id)
        experiment_ids[experiment.experiment_id] = eid
        experiments.append(ExperimentRecord(
            experiment_id=eid,
            experiment_type=experiment.experiment_type,
            material_ids=resolved_materials,
            target=environment.medium if environment and environment.medium else "corrosion performance",
            conditions=conditions,
            outputs=outputs,
            protocol="Corrosion V1 source-reported protocol",
            evidence=_canonical_evidence(experiment.evidence, sid),
        ))
        for mid in resolved_materials:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "tested_in", eid),
                subject_id=mid,
                predicate="tested_in",
                object_id=eid,
                evidence=_canonical_evidence(experiment.evidence, sid),
            ))

    calculations: list[CalculationRecord] = []
    for calculation in document.calculations:
        path = f"calculations.{calculation.calculation_id}"
        if calculation.ownership != "focal_work":
            audit.reject(path, f"ownership_{calculation.ownership}", calculation, ownership=calculation.ownership)
            continue
        resolved_materials = [material_ids[ref] for ref in calculation.material_refs if ref in material_ids]
        if len(resolved_materials) != len(calculation.material_refs) or not _verified(calculation.evidence):
            audit.reject(path, "unresolved_material_or_evidence", calculation, ownership=calculation.ownership)
            continue
        outputs: list[Measurement] = []
        for index, output in enumerate(calculation.outputs):
            if not _verified(output.evidence) or output.quantity.value is None:
                audit.reject(f"{path}.outputs.{index}", "no_verified_value_specific_evidence", output,
                             ownership=calculation.ownership)
                continue
            outputs.append(_measurement(output.property, output.quantity, evidence=output.evidence, sid=sid))
        cid = stable_id("calc", sid, calculation.calculation_id)
        calculations.append(CalculationRecord(
            calculation_id=cid,
            calculation_type=calculation.calculation_type,
            material_ids=resolved_materials,
            method=calculation.method,
            model={
                "surface": calculation.surface,
                "adsorbate_or_inhibitor": calculation.adsorbate_or_inhibitor,
                "reported_parameters": calculation.parameters,
            },
            outputs=outputs,
            evidence=_canonical_evidence(calculation.evidence, sid),
        ))
        for mid in resolved_materials:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "calculated_for", cid),
                subject_id=mid,
                predicate="calculated_for",
                object_id=cid,
                evidence=_canonical_evidence(calculation.evidence, sid),
            ))

    archive = SynthexArchive(
        metadata=ArchiveMetadata(
            archive_id=archive_id,
            extractor_model=model,
            domain="corrosion",
        ),
        sources=[source],
        materials=materials,
        processes=processes,
        experiments=experiments,
        calculations=calculations,
        relationships=relationships,
        domain_payloads=[DomainPayload(
            domain="corrosion",
            schema_version="1.0-stage2",
            tags=document.paper_types,
            values={
                "scope_status": document.scope_status,
                "paper_types": document.paper_types,
                "condition_conflicts": [item.model_dump(mode="json", exclude_none=True) for item in document.condition_conflicts],
                "extraction_notes": list(document.extraction_notes),
                "admissibility_audit": audit.payload(),
            },
        )],
    )
    return score_archive(archive)
