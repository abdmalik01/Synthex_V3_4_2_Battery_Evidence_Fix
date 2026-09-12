from __future__ import annotations

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import stable_id, source_id
from synthex_platform.core.models import (
    CalculationRecord, DomainPayload, ExperimentRecord, MaterialEntity,
    ProcessStep, Relationship, SourceRecord
)
from synthex_platform.core.quality import score_archive
from .draft_models import ExtractedDocument


class _GenericAdmissibilityGate:
    """Keep non-focal generic extraction objects auditable without making them canonical."""

    def __init__(self):
        self.quarantine: list[dict] = []

    def admit(self, kind: str, item) -> bool:
        ownership = item.ownership
        evidence = list(item.evidence)
        if ownership != "focal_work":
            reason = f"ownership_{ownership}"
        elif not any(evidence_item.text_snippet for evidence_item in evidence):
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
    gate = _GenericAdmissibilityGate()

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

    processes = []
    experiments = []
    calculations = []
    relationships = []

    for i, item in enumerate(draft.processes):
        if not gate.admit("process", item):
            continue
        pid = stable_id("proc", sid, item.local_id, item.name)
        local_map[item.local_id] = pid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
        if item.material_refs and not refs:
            gate.quarantine.append({"kind": "process", "local_id": item.local_id, "ownership": item.ownership, "reason": "material_dependencies_not_admitted", "raw_object": item.model_dump(mode="json", exclude_none=True)})
            continue
        processes.append(ProcessStep(
            process_id=pid, name=item.name, family=item.family, sequence_index=i,
            inputs=refs, outputs=refs, parameters=item.parameters, atmosphere=item.atmosphere,
            equipment=item.equipment, evidence=item.evidence,
        ))
        for mid in refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "processed_by", pid),
                subject_id=mid, predicate="processed_by", object_id=pid,
            ))

    for item in draft.experiments:
        if not gate.admit("experiment", item):
            continue
        eid = stable_id("exp", sid, item.local_id, item.experiment_type)
        local_map[item.local_id] = eid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
        if item.material_refs and not refs:
            gate.quarantine.append({"kind": "experiment", "local_id": item.local_id, "ownership": item.ownership, "reason": "material_dependencies_not_admitted", "raw_object": item.model_dump(mode="json", exclude_none=True)})
            continue
        experiments.append(ExperimentRecord(
            experiment_id=eid, experiment_type=item.experiment_type, material_ids=refs,
            target=item.target, conditions=item.conditions, outputs=item.outputs,
            protocol=item.protocol, evidence=item.evidence,
        ))
        for mid in refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "tested_in", eid),
                subject_id=mid, predicate="tested_in", object_id=eid,
            ))

    for item in draft.calculations:
        if not gate.admit("calculation", item):
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
            parameters=item.parameters, outputs=item.outputs, evidence=item.evidence,
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
        sources=[source], materials=materials, processes=processes, experiments=experiments,
        calculations=calculations, relationships=relationships,
        domain_payloads=[DomainPayload(domain=domain, schema_version="1.0.0", values={
            **draft.domain_values,
            "admissibility": {
                "policy": "generic_focal_work_with_source_evidence_v1",
                "quarantined_objects": gate.quarantine,
            },
        })],
    )
    return score_archive(archive)
