"""Dedicated, conservative Catalysis V1 archive assembly."""

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
    QualityRecord,
    Relationship,
    SourceRecord,
    SourceType,
)
from synthex_platform.core.quality import score_archive

from .catalysis_models import CatalysisDocument, CatalysisEvidence
from .catalysis_normalizer import (
    comparability_status,
    normalization_key,
    potential_comparability_key,
    potential_conversion_warning,
)
from .catalysis_postprocess import decide_quantitative_admission, postprocess_catalysis_document
from .source_context import SourceBundle


def _canonical_evidence(items: Iterable[CatalysisEvidence], sid: str) -> list[Evidence]:
    converted: list[Evidence] = []
    for item in items:
        try:
            source_type = SourceType(item.source_type)
        except ValueError:
            source_type = SourceType.unknown
        converted.append(
            Evidence(
                source_id=item.source_id or sid,
                page=item.page,
                section=item.section,
                source_type=source_type,
                original_source_type=item.original_source_type,
                verbatim_match=item.verbatim_match,
                text_snippet=item.text_snippet,
                table_id=item.table_id,
                figure_id=item.figure_id,
                locator=item.locator or (
                    f"row={item.row};column={item.column};cell_id={item.cell_id or ''}"
                    if item.row is not None and item.column is not None else None
                ),
                confidence=item.confidence,
            )
        )
    return converted


def _has_verified_evidence(items: Iterable[CatalysisEvidence]) -> bool:
    return any(item.verbatim_match is True and item.original_source_type != "figure_digitized" for item in items)


class _Audit:
    def __init__(self) -> None:
        self.admitted = 0
        self.quarantine: list[dict] = []

    def reject(self, path: str, reason: str, obj, *, ownership: str | None = None) -> None:
        self.quarantine.append(
            {
                "path": path,
                "reason": reason,
                **({"ownership": ownership} if ownership else {}),
                "object": obj.model_dump(mode="json", exclude_none=True) if hasattr(obj, "model_dump") else obj,
            }
        )

    def measurement(
        self,
        *,
        path: str,
        property_name: str,
        metric,
        evidence: list[CatalysisEvidence],
        ownership: str,
        scope_status: str,
        sid: str,
        conditions: dict,
        unresolved_conflict: bool,
    ) -> Measurement | None:
        basis = getattr(metric, "normalization_basis", None)
        potential = getattr(metric, "potential", None)
        decision = decide_quantitative_admission(
            ownership=ownership,
            property_name=property_name,
            raw_value=metric.raw_value,
            value=metric.value,
            unit=metric.unit,
            evidence=evidence,
            scope_status=scope_status,
            product=getattr(metric, "product", None),
            reactant=getattr(metric, "reactant", None),
            normalization_kind=basis.kind if basis else None,
            potential_reference=potential.reported_reference if potential else None,
            derived=getattr(metric, "derivation", None) is not None,
            unresolved_conflict=unresolved_conflict,
            semantic_invalid=conditions.pop("_semantic_invalid", False),
        )
        if not decision.admitted:
            self.reject(path, decision.reason or "schema_invalid", metric, ownership=ownership)
            return None
        self.admitted += 1
        return Measurement(
            property=property_name,
            raw_value=metric.raw_value,
            value=metric.value,
            unit=metric.unit,
            qualifier=metric.qualifier,
            conditions={key: value for key, value in conditions.items() if value is not None},
            evidence=_canonical_evidence(evidence, sid),
        )

    def payload(self) -> dict:
        return {
            "policy": "catalysis_focal_value_specific_verified_v1",
            "admitted_quantitative_values": self.admitted,
            "quarantined_objects_or_values": len(self.quarantine),
            "quarantine": self.quarantine,
        }


def _ownership(parent: str, child: str = "unknown") -> str:
    return child if child != "unknown" else parent


def _unresolved_conflict(document: CatalysisDocument, record_ref: str) -> bool:
    return any(item.record_ref == record_ref and item.resolved_value is None for item in document.condition_conflicts)


def _reported_potential_conditions(potential) -> tuple[dict, list[str]]:
    if potential is None:
        return {}, []
    raw = potential.raw_potential
    conditions = {
        "reported_potential_raw": raw.raw_value if raw else None,
        "reported_potential_value": raw.value if raw else None,
        "reported_potential_unit": raw.unit if raw else None,
        "reported_reference": potential.reported_reference,
        "reported_reference_text": potential.reported_reference_text,
        "filling_solution": potential.filling_solution,
        "filling_solution_concentration": potential.filling_solution_concentration.model_dump(exclude_none=True) if potential.filling_solution_concentration else None,
        "pH": potential.pH,
        "temperature": potential.temperature.model_dump(exclude_none=True) if potential.temperature else None,
        "potential_comparability_key": potential_comparability_key(potential),
        "converted_potential": potential.converted_potential.model_dump(exclude_none=True) if potential.converted_potential else None,
        "converted_reference": potential.converted_reference,
        "conversion_status": potential.conversion_status,
        "author_formula": potential.author_formula,
    }
    warning = potential_conversion_warning(potential)
    return conditions, [warning] if warning else []


def assemble_catalysis_archive(
    document: CatalysisDocument,
    model: str | None = None,
    source_text: str = "",
    source_bundle: SourceBundle | None = None,
) -> SynthexArchive:
    document, warnings = postprocess_catalysis_document(document, source_text, source_bundle)
    checksum = source_bundle.source.source_checksum if source_bundle else None
    sid = source_id(document.source.doi, document.source.title, checksum)
    archive_id = stable_id("arc", sid, "catalysis")
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
    relationships = [
        Relationship(
            relation_id=stable_id("rel", archive_id, "reported_by", sid),
            subject_id=archive_id,
            predicate="reported_by",
            object_id=sid,
        )
    ]

    candidate_material_ids = {
        item.local_id: stable_id("mat", sid, item.local_id) for item in document.catalysts
    }
    material_ids: dict[str, str] = {}
    materials: list[MaterialEntity] = []
    for item in document.catalysts:
        if item.ownership != "focal_work":
            audit.reject(f"catalysts.{item.local_id}", f"ownership_{item.ownership}", item, ownership=item.ownership)
            continue
        if document.scope_status != "supported":
            audit.reject(f"catalysts.{item.local_id}", "unsupported_v1_subtype", item, ownership=item.ownership)
            continue
        if not _has_verified_evidence(item.evidence):
            audit.reject(f"catalysts.{item.local_id}", "no_value_specific_evidence", item, ownership=item.ownership)
            continue
        mid = candidate_material_ids[item.local_id]
        material_ids[item.local_id] = mid
        materials.append(
            MaterialEntity(
                material_id=mid,
                name=item.canonical_name or item.reported_name or item.formula or item.reported_formula,
                formula=item.formula or item.reported_formula,
                composition=item.composition,
                phase=item.phase,
                structure={
                    "catalyst_state": item.state,
                    "components": [
                        {
                            "role": component.role,
                            "reported_name": component.reported_name,
                            "formula": component.formula,
                            "material_ref": component.material_ref,
                        }
                        for component in item.components
                    ],
                },
                morphology={"description": item.morphology} if item.morphology else {},
                tags=["catalyst", f"state:{item.state}", f"ownership:{item.ownership}"],
                evidence=_canonical_evidence(item.evidence, sid),
            )
        )

    for item in document.catalysts:
        mid = material_ids.get(item.local_id)
        if not mid:
            continue
        for component in item.components:
            target = material_ids.get(component.material_ref or "")
            if not target or not _has_verified_evidence(component.evidence):
                continue
            predicate = {"support": "supported_on", "promoter": "promoted_by"}.get(component.role)
            if predicate:
                relationships.append(Relationship(
                    relation_id=stable_id("rel", mid, predicate, target),
                    subject_id=mid, predicate=predicate, object_id=target,
                    evidence=_canonical_evidence(component.evidence, sid),
                ))
        parent = material_ids.get(item.state_parent_ref or item.variant_of or "")
        if parent:
            relationships.append(Relationship(
                relation_id=stable_id("rel", mid, "derived_from", parent),
                subject_id=mid, predicate="derived_from", object_id=parent,
                attributes={"state": item.state}, evidence=_canonical_evidence(item.evidence, sid),
            ))

    processes: list[ProcessStep] = []
    for preparation in document.preparations:
        output_id = material_ids.get(preparation.material_ref or "")
        if preparation.ownership != "focal_work" or not output_id:
            audit.reject(
                f"preparations.{preparation.preparation_id}",
                f"ownership_{preparation.ownership}" if preparation.ownership != "focal_work" else "schema_invalid",
                preparation,
                ownership=preparation.ownership,
            )
            continue
        for index, step in enumerate(preparation.steps):
            evidence = step.evidence or preparation.evidence
            if not _has_verified_evidence(evidence):
                audit.reject(f"preparations.{preparation.preparation_id}.steps.{index}", "no_value_specific_evidence", step)
                continue
            process_id = stable_id("proc", sid, preparation.preparation_id, index)
            parameters = []
            for prop, quantity in (("temperature", step.temperature), ("duration", step.duration)):
                if quantity is None:
                    continue
                metric = quantity
                admitted = audit.measurement(
                    path=f"preparations.{preparation.preparation_id}.steps.{index}.{prop}",
                    property_name=prop, metric=metric, evidence=evidence,
                    ownership=preparation.ownership, scope_status=document.scope_status,
                    sid=sid, conditions={}, unresolved_conflict=False,
                )
                if admitted:
                    parameters.append(admitted)
            processes.append(ProcessStep(
                process_id=process_id, name=step.step, family="catalyst_preparation",
                sequence_index=index, inputs=step.precursors, outputs=[output_id],
                parameters=parameters, atmosphere=step.atmosphere,
                evidence=_canonical_evidence(evidence, sid),
            ))
            relationships.append(Relationship(
                relation_id=stable_id("rel", output_id, "processed_by", process_id),
                subject_id=output_id, predicate="processed_by", object_id=process_id,
                evidence=_canonical_evidence(evidence, sid),
            ))

    experiments: list[ExperimentRecord] = []
    experiment_material: dict[str, str] = {}

    def assemble_experiment(experiment, *, electrochemical: bool) -> None:
        material_id = material_ids.get(experiment.catalyst_ref or "")
        if experiment.ownership != "focal_work" or not material_id or document.scope_status != "supported":
            reason = (
                f"ownership_{experiment.ownership}" if experiment.ownership != "focal_work"
                else "unsupported_v1_subtype" if document.scope_status != "supported"
                else "schema_invalid"
            )
            audit.reject(f"experiments.{experiment.experiment_id}", reason, experiment, ownership=experiment.ownership)
            return
        outputs: list[Measurement] = []
        conflict = _unresolved_conflict(document, experiment.experiment_id)
        for index, metric in enumerate(experiment.metrics):
            evidence = metric.evidence or experiment.evidence
            basis = metric.normalization_basis
            potential = getattr(metric, "potential", None)
            potential_conditions, potential_warnings = _reported_potential_conditions(potential)
            warnings.extend(potential_warnings)
            conditions = {
                "reaction": experiment.reaction.reported_reaction,
                "reaction_class": experiment.reaction.reaction_class,
                "reactant": getattr(metric, "reactant", None),
                "product": getattr(metric, "product", None),
                "normalization_basis": basis.model_dump(mode="json", exclude_none=True) if basis else None,
                "normalization_key": normalization_key(basis),
                "comparability_status": comparability_status(basis),
                "_semantic_invalid": bool(
                    electrochemical and experiment.pH is not None and not 0 <= experiment.pH <= 14
                ),
                **potential_conditions,
            }
            measurement = audit.measurement(
                path=f"experiments.{experiment.experiment_id}.metrics.{index}",
                property_name=metric.property, metric=metric, evidence=evidence,
                ownership=_ownership(experiment.ownership, metric.ownership),
                scope_status=document.scope_status, sid=sid, conditions=conditions,
                unresolved_conflict=conflict,
            )
            if measurement:
                outputs.append(measurement)
        if not outputs:
            audit.reject(f"experiments.{experiment.experiment_id}", "no_value_specific_evidence", experiment, ownership=experiment.ownership)
            return
        experiment_id = stable_id("exp", sid, experiment.experiment_id)
        conditions: list[Measurement] = []
        condition_names = (
            ("catalyst_loading", "electrolyte_concentration", "temperature")
            if electrochemical else ("catalyst_mass", "temperature", "pressure", "whsv", "ghsv")
        )
        for name in condition_names:
            quantity = getattr(experiment, name, None)
            if quantity is not None:
                admitted_condition = audit.measurement(
                    path=f"experiments.{experiment.experiment_id}.{name}",
                    property_name=name, metric=quantity, evidence=experiment.evidence,
                    ownership=experiment.ownership, scope_status=document.scope_status,
                    sid=sid, conditions={}, unresolved_conflict=conflict,
                )
                if admitted_condition:
                    conditions.append(admitted_condition)
        experiments.append(ExperimentRecord(
            experiment_id=experiment_id,
            experiment_type="electrocatalysis" if electrochemical else "heterogeneous_catalysis",
            material_ids=[material_id], target=experiment.reaction.reported_reaction,
            conditions=conditions, outputs=outputs, evidence=_canonical_evidence(experiment.evidence, sid),
        ))
        experiment_material[experiment.experiment_id] = material_id
        relationships.append(Relationship(
            relation_id=stable_id("rel", material_id, "tested_in", experiment_id),
            subject_id=material_id, predicate="tested_in", object_id=experiment_id,
            evidence=_canonical_evidence(experiment.evidence, sid),
        ))
        product_evidence = {
            output.conditions.get("product"): output.evidence
            for output in outputs if output.conditions.get("product")
        }
        for product, evidence in product_evidence.items():
            product_id = stable_id("mat", sid, "product", product)
            if not any(item.material_id == product_id for item in materials):
                materials.append(MaterialEntity(
                    material_id=product_id, name=product,
                    tags=["reaction_product"], evidence=evidence,
                ))
            relationships.append(Relationship(
                relation_id=stable_id("rel", experiment_id, "reports", product_id),
                subject_id=experiment_id, predicate="reports", object_id=product_id,
                evidence=evidence,
            ))

    for item in document.heterogeneous_experiments:
        assemble_experiment(item, electrochemical=False)
    for item in document.electrocatalysis_experiments:
        assemble_experiment(item, electrochemical=True)

    for stability in document.stability_tests:
        material_id = experiment_material.get(stability.experiment_ref or "")
        metric = stability.retained_metric
        if stability.ownership != "focal_work" or not material_id or metric is None:
            audit.reject(f"stability_tests.{stability.stability_id}", f"ownership_{stability.ownership}" if stability.ownership != "focal_work" else "schema_invalid", stability, ownership=stability.ownership)
            continue
        evidence = metric.evidence or stability.evidence
        potential_conditions, potential_warnings = _reported_potential_conditions(stability.operating_potential)
        warnings.extend(potential_warnings)
        conditions = {
            "mode": stability.mode,
            "duration": stability.duration.model_dump(exclude_none=True) if stability.duration else None,
            "cycle_count": stability.cycle_count,
            "operating_current": stability.operating_current.model_dump(exclude_none=True) if stability.operating_current else None,
            "operating_temperature": stability.operating_temperature.model_dump(exclude_none=True) if stability.operating_temperature else None,
            "reaction_conditions": stability.reaction_conditions,
            "catalyst_state_ref": stability.catalyst_state_ref,
            "catalyst_state": next((x.state for x in document.catalysts if x.local_id == (stability.catalyst_state_ref or next((e.catalyst_ref for e in [*document.heterogeneous_experiments, *document.electrocatalysis_experiments] if e.experiment_id == stability.experiment_ref), None))), "unknown"),
            **potential_conditions,
        }
        output = audit.measurement(
            path=f"stability_tests.{stability.stability_id}.retained_metric",
            property_name=metric.property, metric=metric, evidence=evidence,
            ownership=_ownership(stability.ownership, metric.ownership),
            scope_status=document.scope_status, sid=sid, conditions=conditions,
            unresolved_conflict=_unresolved_conflict(document, stability.stability_id),
        )
        if output:
            experiments.append(ExperimentRecord(
                experiment_id=stable_id("exp", sid, stability.stability_id),
                experiment_type="catalyst_stability", material_ids=[material_id],
                conditions=[], outputs=[output],
                protocol=stability.regeneration_details,
                evidence=_canonical_evidence(stability.evidence, sid),
            ))

    calculations: list[CalculationRecord] = []
    for calculation in document.calculations:
        material_refs = [material_ids[item] for item in calculation.material_refs if item in material_ids]
        if calculation.ownership != "focal_work" or not material_refs or document.scope_status != "supported":
            reason = f"ownership_{calculation.ownership}" if calculation.ownership != "focal_work" else "unsupported_v1_subtype" if document.scope_status != "supported" else "schema_invalid"
            audit.reject(f"calculations.{calculation.calculation_id}", reason, calculation, ownership=calculation.ownership)
            continue
        outputs = []
        for index, metric in enumerate(calculation.outputs):
            evidence = metric.evidence or calculation.evidence
            measurement = audit.measurement(
                path=f"calculations.{calculation.calculation_id}.outputs.{index}",
                property_name=metric.property, metric=metric, evidence=evidence,
                ownership=_ownership(calculation.ownership, metric.ownership),
                scope_status=document.scope_status, sid=sid,
                conditions={"adsorbate_or_intermediate": metric.adsorbate_or_intermediate, "site": metric.site, "facet": metric.facet},
                unresolved_conflict=_unresolved_conflict(document, calculation.calculation_id),
            )
            if measurement:
                outputs.append(measurement)
        if not outputs:
            audit.reject(f"calculations.{calculation.calculation_id}", "no_value_specific_evidence", calculation, ownership=calculation.ownership)
            continue
        calculation_id = stable_id("calc", sid, calculation.calculation_id)
        calculations.append(CalculationRecord(
            calculation_id=calculation_id, calculation_type=calculation.calculation_type,
            material_ids=material_refs, code=calculation.code, method=calculation.calculation_type,
            functional=calculation.functional,
            model={
                "dispersion_correction": calculation.dispersion_correction,
                "plane_wave_cutoff_or_basis": calculation.plane_wave_cutoff_or_basis,
                "k_points": calculation.k_points,
                "slab_or_facet": calculation.slab_or_facet,
                "layers": calculation.layers,
                "solvation_model": calculation.solvation_model,
                "adsorbate_coverage": calculation.adsorbate_coverage,
                "spin_treatment": calculation.spin_treatment,
                "vacuum_thickness": calculation.vacuum_thickness.model_dump(exclude_none=True) if calculation.vacuum_thickness else None,
            },
            outputs=outputs, evidence=_canonical_evidence(calculation.evidence, sid),
        ))
        for material_id in material_refs:
            relationships.append(Relationship(
                relation_id=stable_id("rel", material_id, "calculated_for", calculation_id),
                subject_id=material_id, predicate="calculated_for", object_id=calculation_id,
                evidence=_canonical_evidence(calculation.evidence, sid),
            ))

    audit_payload = audit.payload()
    canonical_record_count = len(materials) + len(processes) + len(experiments) + len(calculations)
    audit_payload["canonical_admission_count"] = canonical_record_count
    payload = {
        "validated_document": document.model_dump(mode="json"),
        "admissibility_audit": audit_payload,
        "quarantined_objects_measurements": audit.quarantine,
        "normalization_comparability_warnings": list(dict.fromkeys(warnings)),
        "conflicts": [item.model_dump(mode="json") for item in document.condition_conflicts],
        "extraction_notes": document.extraction_notes,
    }
    if source_bundle is not None:
        payload["source_context"] = source_bundle.parser_metadata()

    semantic_warnings = list(dict.fromkeys([
        *warnings,
        f"canonical_admission_count:{canonical_record_count}",
        f"quarantine_count:{len(audit.quarantine)}",
        f"unresolved_conflict_count:{sum(item.resolved_value is None for item in document.condition_conflicts)}",
    ]))
    archive = SynthexArchive(
        metadata=ArchiveMetadata(archive_id=archive_id, extractor_model=model, domain="catalysis"),
        sources=[source], materials=materials, processes=processes,
        experiments=experiments, calculations=calculations, relationships=relationships,
        domain_payloads=[DomainPayload(domain="catalysis", schema_version="1.0-stage2", values=payload)],
        quality=QualityRecord(semantic_warnings=semantic_warnings),
    )
    score_archive(archive)
    total = audit.admitted + len(audit.quarantine)
    if total:
        archive.quality.completeness *= audit.admitted / total
        archive.quality.extraction_confidence = audit.admitted / total
    return archive
