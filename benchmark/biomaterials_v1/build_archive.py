"""Build specimen-linked canonical archives from locked offline source recovery."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import re

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation, DraftDevice, DraftDeviceLayer, DraftExperiment, DraftMaterial, DraftProcess,
    DraftSource, ExtractedDocument,
)

from .offline_recovery import (
    LOCKS, computational_method_e, formulation_a, formulations_h, mixed_process_h,
    negative_route_g, process_parameters_d, recover, review_cited_values_f,
)


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.casefold().replace("+", "_plus")).strip("_")


def _evidence(source: dict) -> Evidence:
    return Evidence(page=source["page"], source_type=SourceType(source["source_type"]),
                    verbatim_match=True, text_snippet=source["text_snippet"],
                    table_id=source.get("table_id"), locator=source["locator"])


def _measurement(row: dict) -> Measurement:
    context = {**row.get("context", {}), "sample_label": row["sample_label"],
               "scientific_type": row["scientific_type"]}
    return Measurement(property=row["property"], raw_value=row["raw_value"], value=row["value"],
                       unit=row["unit"], method=context.get("assay") or context.get("method"),
                       conditions=context, qualifier="exact", evidence=[_evidence(row["evidence"])])


def _source(lock: dict) -> DraftSource:
    return DraftSource(title=lock["title"], doi=lock["doi"], url=lock["official_url"],
                       year=lock["year"], authors=[part.strip() for part in lock["authors"].split(",")])


def _nonexperimental_draft(case_id: str) -> ExtractedDocument:
    lock = LOCKS[case_id]
    domain_values = {"case_id": case_id, "source_pdf_sha256": lock["pdf_sha256"],
                     "gold_sha256": lock["gold_sha256"], "provider_invoked": False}
    if case_id == "BIO-NEG-G":
        return ExtractedDocument(source=_source(lock), domain_values={**domain_values,
            "negative_control": True, "routing": negative_route_g()})
    if case_id == "BIO-REVIEW-F":
        audit = review_cited_values_f()
        materials = []
        experiments = []
        for index, cited in enumerate(audit["cited_values"]):
            evidence = _evidence(cited["evidence"])
            mid = "cited_material_" + str(index)
            materials.append(DraftMaterial(local_id=mid, name=cited["label"],
                tags=["review_table", "cited_prior_work"], ownership="cited_prior_work", evidence=[evidence]))
            output = Measurement(property=cited["property"], raw_value=cited["raw_value"],
                value=cited["value"], unit=cited["unit"], qualifier="exact",
                conditions={"scientific_type": "reported_measurement", "ownership": "cited_prior_work",
                            "citation_reference": cited["reference"], "sample_label": cited["label"]},
                evidence=[evidence])
            experiments.append(DraftExperiment(local_id="cited_experiment_" + str(index),
                experiment_type="review_comparison_table_entry", material_refs=[mid],
                outputs=[output], ownership="cited_prior_work", evidence=[evidence]))
        return ExtractedDocument(source=_source(lock), materials=materials, experiments=experiments,
            domain_values={**domain_values, "article_type": "Review",
                           "review_detection": {k: audit[k] for k in ("publisher_review_signal", "author_self_description")},
                           "noncanonical_cited_count": len(audit["cited_values"])})
    if case_id == "BIO-COMPUTE-E":
        method = computational_method_e()
        materials = []
        calculations = []
        material_ids = set()
        by_system: dict[str, list[dict]] = defaultdict(list)
        for row in recover(case_id)["outputs"]:
            by_system[row["sample_label"]].append(row)
        for label, rows in by_system.items():
            surface = rows[0]["context"]["surface_model"]
            mid = "mat_" + _key(surface)
            evidence = _evidence(rows[0]["evidence"])
            if mid not in material_ids:
                materials.append(DraftMaterial(local_id=mid, name=surface, formula="Ca10(PO4)6(OH)2",
                    tags=["hydroxyapatite", "simulation_surface_model"], ownership="focal_work",
                    evidence=[evidence]))
                material_ids.add(mid)
            calculations.append(DraftCalculation(local_id="calc_" + _key(label),
                calculation_type="molecular_dynamics_surface_biomolecule_interaction",
                material_refs=[mid], code=method["code"], method="molecular dynamics",
                model={**method, "system": label, "biomolecule": rows[0]["context"]["biomolecule"],
                       "solvent_for_system": rows[0]["context"]["solvent"]},
                outputs=[_measurement(row) for row in rows], ownership="focal_work", evidence=[evidence]))
        return ExtractedDocument(source=_source(lock), materials=materials, calculations=calculations,
            domain_values={**domain_values, "focal_modality": "computational"})
    raise ValueError(f"Unsupported nonexperimental case: {case_id}")


def build_draft(case_id: str) -> ExtractedDocument:
    if case_id in {"BIO-COMPUTE-E", "BIO-REVIEW-F", "BIO-NEG-G"}:
        return _nonexperimental_draft(case_id)
    lock = LOCKS[case_id]
    rows = recover(case_id)["outputs"]
    by_specimen: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_specimen[(row["sample_label"], row["context"].get("specimen_type", "scaffold"))].append(row)
    materials = []
    devices = []
    processes = []
    experiments = []
    material_ids: set[str] = set()
    shared_a_formulation = formulation_a() if case_id == "BIO-GOLD-A" else None
    mixed_h_formulations = formulations_h() if case_id == "BIO-MIXED-H" else None
    for (label, specimen_type), specimen_rows in by_specimen.items():
        suffix = _key(label) + "_" + specimen_type
        material_id = "mat_shared_gelatin_alginate_c3a" if shared_a_formulation else "mat_" + _key(label)
        device_id = "dev_" + suffix
        evidence_row = specimen_rows[0]
        source_evidence = evidence_row["evidence"]
        evidence = Evidence(page=source_evidence["page"], source_type=SourceType(source_evidence["source_type"]),
                            verbatim_match=True, text_snippet=source_evidence["text_snippet"],
                            table_id=source_evidence.get("table_id"), locator=source_evidence["locator"])
        if shared_a_formulation:
            material_evidence = Evidence(page=shared_a_formulation["evidence_page"], source_type=SourceType.text,
                verbatim_match=True, text_snippet=shared_a_formulation["evidence_snippet"], locator="Methods; hydrogel preparation")
            material_name = shared_a_formulation["name"]
        elif mixed_h_formulations:
            formulation = mixed_h_formulations[label]
            material_evidence = Evidence(page=formulation["evidence_page"], source_type=SourceType.text,
                verbatim_match=True, text_snippet=formulation["evidence_snippet"],
                locator=f"page=2;S1-S5 formulation;sample={label}")
            material_name = f"{formulation['alginate_wv_percent']}% w/v sodium alginate + 4% w/v gelatin"
        else:
            material_evidence, material_name = evidence, label
        if material_id not in material_ids:
            materials.append(DraftMaterial(local_id=material_id, name=material_name,
                tags=["biomaterial_formulation"], ownership="focal_work", evidence=[material_evidence]))
            material_ids.add(material_id)
        if specimen_type == "filament":
            device_type = "biomaterial_filament"
        elif case_id == "BIO-BIOACT-B" or specimen_type == "hydrogel":
            device_type = "biomaterial_hydrogel"
        else:
            device_type = "biomaterial_scaffold"
        devices.append(DraftDevice(
            local_id=device_id, name=f"{label} {specimen_type}", device_type=device_type,
            layer_stack=[DraftDeviceLayer(sequence_index=0, role="bulk_formulation", material_ref=material_id, evidence=[material_evidence])],
            configuration={"sample_label": label, "specimen_type": specimen_type,
                           **({"alginate_wv_percent": mixed_h_formulations[label]["alginate_wv_percent"],
                               "gelatin_wv_percent": 4} if mixed_h_formulations else {}),
                           **({"formulation": shared_a_formulation["name"],
                               "gelatin_stock_wv_percent": shared_a_formulation["gelatin_stock_wv_percent"],
                               "alginate_stock_wv_percent": shared_a_formulation["alginate_stock_wv_percent"],
                               "stock_volume_ratio": shared_a_formulation["stock_volume_ratio"],
                               "encapsulation_density_raw": shared_a_formulation["cell_density_raw"]} if shared_a_formulation else {})},
            ownership="focal_work", evidence=[evidence],
        ))
        process_name = specimen_rows[0]["context"].get("process") or {
            "BIO-BIOACT-B": "hydrogel crosslinking", "BIO-DEGR-C": "3D printing and freeze drying",
        }.get(case_id, "specimen fabrication")
        process_parameters = []
        if case_id == "BIO-PROCESS-D" and specimen_type == "scaffold":
            for parameter in process_parameters_d():
                source = parameter["evidence"]
                process_parameters.append(Measurement(
                    property=parameter["property"], raw_value=parameter["raw_value"],
                    value=parameter["value"], unit=parameter["unit"],
                    conditions={"sample_label": label, "scientific_type": "reported_process_parameter"},
                    qualifier="exact", evidence=[Evidence(
                        page=source["page"], source_type=SourceType.table, table_id=source["table_id"],
                        locator=source["locator"], text_snippet=source["text_snippet"], verbatim_match=True,
                    )],
                ))
        if case_id == "BIO-MIXED-H" and specimen_type == "scaffold":
            parameter = next(item for item in mixed_process_h() if item["sample_label"] == label)
            process_parameters.append(Measurement(property="extrusion_pressure",
                raw_value=parameter["raw_value"], value=parameter["value"], unit="kPa",
                qualifier="approx", conditions={"sample_label": label,
                    "scientific_type": "reported_process_parameter", "approximate": True},
                evidence=[_evidence(parameter["evidence"])]))
        processes.append(DraftProcess(
            local_id="proc_" + suffix, name=process_name, family="biomaterial_fabrication",
            input_material_refs=[material_id], output_device_refs=[device_id],
            parameters=process_parameters, ownership="focal_work", evidence=[evidence],
        ))
        groups: dict[tuple, list[Measurement]] = defaultdict(list)
        for row in specimen_rows:
            context = {**row["context"], "sample_label": label, "scientific_type": row["scientific_type"]}
            source = row["evidence"]
            measurement = Measurement(
                property=row["property"], raw_value=row["raw_value"], value=row["value"], unit=row["unit"],
                method=context.get("assay"), conditions=context,
                qualifier="exact", evidence=[Evidence(page=source["page"], source_type=SourceType(source["source_type"]),
                    verbatim_match=True, text_snippet=source["text_snippet"], locator=source["locator"],
                    table_id=source.get("table_id"))],
            )
            group_key = tuple(context.get(k) for k in ("assay", "exposure_time", "organism", "strain", "dilution", "medium"))
            groups[group_key].append(measurement)
        for index, (context_key, outputs) in enumerate(groups.items()):
            assay = context_key[0] or "physicochemical_characterization"
            experiments.append(DraftExperiment(
                local_id=f"exp_{suffix}_{index}", experiment_type=assay,
                material_refs=[material_id], device_refs=[device_id], outputs=outputs,
                ownership="focal_work", evidence=[evidence],
            ))
    draft = ExtractedDocument(
        source=_source(lock),
        materials=materials, devices=devices, processes=processes, experiments=experiments,
        domain_values={"case_id": case_id, "source_pdf_sha256": lock["pdf_sha256"], "gold_sha256": lock["gold_sha256"]},
    )
    return draft


def build_archive(case_id: str):
    return assemble_archive(build_draft(case_id), "biomaterials", model="offline_source_table_recovery_v1")


if __name__ == "__main__":
    for case in LOCKS:
        archive = build_archive(case)
        quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
        print(case, "materials", len(archive.materials), "specimens", len(archive.devices),
              "processes", len(archive.processes), "experiments", len(archive.experiments),
              "calculations", len(archive.calculations),
              "outputs", sum(len(e.outputs) for e in archive.experiments)
                         + sum(len(c.outputs) for c in archive.calculations),
              "quarantine", len(quarantine))
