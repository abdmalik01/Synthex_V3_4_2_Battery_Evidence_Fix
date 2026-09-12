from __future__ import annotations

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.identifiers import stable_id, source_id
from synthex_platform.core.models import (
    CalculationRecord, DomainPayload, ExperimentRecord, MaterialEntity,
    ProcessStep, Relationship, SourceRecord
)
from synthex_platform.core.quality import score_archive
from .draft_models import ExtractedDocument


def assemble_archive(draft: ExtractedDocument, domain: str, model: str | None = None) -> SynthexArchive:
    sid = source_id(draft.source.doi, draft.source.title)
    archive_id = stable_id("arc", sid, domain)
    local_map: dict[str, str] = {}

    materials = []
    for item in draft.materials:
        mid = stable_id("mat", sid, item.local_id, item.formula or "", item.name or "")
        local_map[item.local_id] = mid
        materials.append(MaterialEntity(
            material_id=mid, name=item.name, formula=item.formula, composition=item.composition,
            elements=item.elements, phase=item.phase, morphology=item.morphology,
            defects=item.defects, dopants=item.dopants, tags=item.tags,
        ))

    processes = []
    experiments = []
    calculations = []
    relationships = []

    for i, item in enumerate(draft.processes):
        pid = stable_id("proc", sid, item.local_id, item.name)
        local_map[item.local_id] = pid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
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
        eid = stable_id("exp", sid, item.local_id, item.experiment_type)
        local_map[item.local_id] = eid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
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
        cid = stable_id("calc", sid, item.local_id, item.calculation_type)
        local_map[item.local_id] = cid
        refs = [local_map[r] for r in item.material_refs if r in local_map]
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
        domain_payloads=[DomainPayload(domain=domain, schema_version="1.0.0", values=draft.domain_values)],
    )
    return score_archive(archive)
