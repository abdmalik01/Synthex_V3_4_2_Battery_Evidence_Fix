"""Deterministic recovery for Membranes V1 closure cases E-H."""

from __future__ import annotations

import pymupdf

from synthex_platform.core.models import Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation,
    DraftDevice,
    DraftDeviceLayer,
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    ExtractedDocument,
)
from synthex_platform.extraction.membranes_review_guard import (
    apply_membranes_review_ownership_guard,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext

from .recover_cases import CASE_DIR, _evidence, _measurement, _source, _verify_locked_case


def _outputs(archive) -> list[Measurement]:
    return [
        output
        for record in [*archive.experiments, *archive.calculations]
        for output in record.outputs
    ]


def recover_compute_e():
    _, gold = _verify_locked_case("source_lock_compute_e.json", {
        4: ("All simulations were performed using NAMD2", "CHARMM36", "310 K", "12 Å"),
        9: ("Table 2", "Calculated membrane permeability of O2 and CO2", "15.9 ± 1.8", "3.1 ± 0.1"),
    })
    materials: list[DraftMaterial] = []
    calculations: list[DraftCalculation] = []
    for index, row in enumerate(gold["rows"], start=1):
        row_id = f"row_{index:02d}"
        label = f"{row['family']} {row['composition']} {row['species']}"
        raw_perm = f"{row['permeability']:g} ± {row['permeability_uncertainty']:g}"
        raw_diff = f"{row['diffusion']:g} ± {row['diffusion_uncertainty']:g}"
        evidence = _evidence(9, "Table 2", label, f"{raw_perm}; {raw_diff}")
        materials.append(DraftMaterial(
            local_id=row_id,
            name=f"simulated lipid bilayer {row['family']} {row['composition']}",
            tags=["lipid bilayer", "computational", row["family"], row["species"]],
            ownership="focal_work",
            evidence=[evidence],
        ))
        common = {
            "scientific_type": "simulation_result",
            "membrane_modality": "computational_transport",
            "species": row["species"],
            "temperature": gold["method"]["temperature"],
            "temperature_unit": gold["method"]["temperature_unit"],
            "pressure": gold["method"]["pressure"],
            "pressure_unit": gold["method"]["pressure_unit"],
            "boundary_conditions": gold["method"]["boundary_conditions"],
            "time_step_fs": gold["method"]["time_step_fs"],
            "gas_copies": gold["method"]["gas_copies"],
            "simulation_method": "NAMD2 molecular dynamics with CHARMM36",
            "lipid_family": row["family"],
            "lipid_composition": row["composition"],
            "analysis_duration_ns": row["duration_ns"],
            "bulk_gas_concentration_mM": row["bulk_concentration_mM"],
            "membrane_area_A2": row["area_A2"],
            "membrane_thickness_A": row["thickness_A"],
        }
        outputs = [
            _measurement(
                "calculated_membrane_permeability_coefficient", raw_perm,
                row["permeability"], "cm/s", evidence, common,
                uncertainty=row["permeability_uncertainty"],
            ),
            _measurement(
                "calculated_apparent_diffusion_coefficient", raw_diff,
                row["diffusion"], "10^-6 cm2/s", evidence, common,
                uncertainty=row["diffusion_uncertainty"],
            ),
        ]
        calculations.append(DraftCalculation(
            local_id=f"calculation_{row_id}",
            calculation_type=gold["method"]["calculation_type"],
            material_refs=[row_id],
            code=gold["method"]["software"],
            method="flooding molecular-dynamics simulation and permeation-event regression",
            functional=gold["method"]["force_field"],
            model={
                **gold["method"],
                "lipid_family": row["family"],
                "lipid_composition": row["composition"],
                "species": row["species"],
            },
            outputs=outputs,
            ownership="focal_work",
            evidence=[evidence],
        ))
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold),
        materials=materials,
        calculations=calculations,
        domain_values={
            "case_id": gold["case_id"],
            "provider_invoked": False,
            "source_table": "Table 2",
            "modality_policy": "simulation outputs remain CalculationRecords",
        },
    ), domain="membranes", model="deterministic_md_table_recovery")
    if (
        len(archive.materials) != gold["expected_materials"]
        or len(archive.calculations) != gold["expected_calculations"]
        or len(_outputs(archive)) != gold["expected_outputs"]
        or archive.experiments
    ):
        raise ValueError("MEM-COMPUTE-E deterministic recovery is incomplete")
    return archive


def recover_review_f():
    lock, gold = _verify_locked_case("source_lock_review_f.json", {
        1: ("Review", "This review addresses", "discussed in this review"),
        42: ("Table 6", "Graphene-like fillers", "3.5 ± 0.6", "22.9 ± 1.1", "[134]"),
    })
    source_path = CASE_DIR / lock["article_file"]
    with pymupdf.open(source_path) as document:
        pages = [
            SourcePageContext(
                page=index + 1,
                native_text=page.get_text(), text=page.get_text(),
                native_parser="pymupdf", parser="pymupdf", origin="native_text", sufficient=True,
            )
            for index, page in enumerate(document)
        ]
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id="mem-review-f", filename=source_path.name,
            source_checksum=lock["article_sha256"],
        ),
        pages=pages,
    )
    example = gold["reviewed_noncanonical_example"]
    evidence = _evidence(
        42, "Table 6", "PIM-1 graphene-like fillers reference [134]",
        "3.5 ± 0.6 × 10^3; 22.9 ± 1.1",
    )
    material = DraftMaterial(
        local_id="pim1_graphene_cited",
        name=example["material"],
        tags=["review comparison", "cited prior work"],
        ownership="focal_work",
        evidence=[evidence],
    )
    device = DraftDevice(
        local_id="cited_membrane",
        name=example["material"],
        device_type="membrane_specimen",
        layer_stack=[DraftDeviceLayer(
            sequence_index=0, role="membrane_body",
            material_ref=material.local_id, evidence=[evidence],
        )],
        configuration={"membrane_modality": "gas_separation", "architecture_type": "dense_mixed_matrix_film"},
        ownership="focal_work",
        evidence=[evidence],
    )
    common = {
        "membrane_modality": "gas_separation",
        "test_mode": "mixed_gas",
        "temperature": example["temperature_C"],
        "temperature_unit": "C",
        "pressure_kind": "feed_pressure",
        "feed_pressure": example["pressure_bar"],
        "feed_composition": example["feed"],
        "cited_reference": example["reference"],
    }
    outputs = [
        _measurement(
            "gas_permeability", "3.5 ± 0.6 × 10^3",
            example["co2_permeability_Barrer"], "Barrer", evidence,
            {**common, "scientific_type": "reported_measurement", "species": "CO2"},
            uncertainty=example["co2_permeability_uncertainty_Barrer"],
        ),
        _measurement(
            "mixed_gas_selectivity", "22.9 ± 1.1", example["selectivity"],
            "dimensionless", evidence,
            {**common, "scientific_type": "reported_derived_metric", "species_pair": "CO2/CH4"},
            uncertainty=example["selectivity_uncertainty"],
        ),
    ]
    draft = ExtractedDocument(
        source=_source(gold),
        materials=[material],
        devices=[device],
        experiments=[DraftExperiment(
            local_id="review_table_6_ref_134",
            experiment_type="review_comparison_table_entry",
            device_refs=[device.local_id],
            target="cited CO2/CH4 separation performance",
            outputs=outputs,
            ownership="focal_work",
            evidence=[evidence],
        )],
        domain_values={"case_id": gold["case_id"], "provider_invoked": False},
    )
    guarded = apply_membranes_review_ownership_guard(draft, bundle)
    archive = assemble_archive(guarded, domain="membranes", model="deterministic_review_guard")
    route = DomainRouter().route_text(bundle.page_marked_text())
    return archive, guarded, route


def recover_neg_g():
    lock, gold = _verify_locked_case("source_lock_neg_g.json", {
        1: ("Porous Separator", "Lithium-Ion Batteries", "electrolyte uptake", "electrochemical performance"),
        10: ("layer-structured PVDF-HFP", "Table 1", "Celgard Separator"),
    })
    with pymupdf.open(CASE_DIR / lock["article_file"]) as document:
        text = "\n".join(page.get_text() for page in document)
    folded = text.casefold()
    if not all(token.casefold() in folded for token in [*gold["misleading_vocabulary"], *gold["battery_vocabulary"]]):
        raise ValueError("MEM-NEG-G vocabulary anchors changed")
    first = DomainRouter().route_text(text)
    second = DomainRouter().route_text(text)
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold),
        domain_values={
            "case_id": gold["case_id"], "provider_invoked": False,
            "negative_control": True, "expected_route": gold["expected_route"],
        },
    ), domain="membranes", model="negative_control_no_provider")
    return archive, first, second


def _thickness(variant: dict, evidence):
    if variant["thickness_um"] is None:
        return None
    raw = f"{variant['thickness_um']:g} ± {variant['thickness_uncertainty_um']:g}"
    return Measurement(
        property="membrane_thickness", raw_value=raw, value=variant["thickness_um"],
        unit="µm", uncertainty=variant["thickness_uncertainty_um"], uncertainty_unit="µm",
        qualifier="exact", conditions={"scientific_type": "reported_measurement", "thickness_scope": "membrane_body"},
        evidence=[evidence.model_copy(update={"text_snippet": f"{evidence.text_snippet}; reported value {raw}"})],
    )


def recover_mixed_h():
    _, gold = _verify_locked_case("source_lock_mixed_h.json", {
        3: ("Table 1", "UF-2P", "stacking two MF-12P", "porous stainless-steel discs"),
        4: ("average pore size of the UF membranes was around 36 nm", "MF membranes was around 180 nm", "0.3 bar"),
        7: ("Table 2", "17.2 ± 0.8", "20.5 ± 0.9"),
        10: ("Table 4", "96.8", "82.7"),
        11: ("75%, 68%, and 67%", "69%, 61%, and 62%"),
        12: ("final flux recoveries of 94% and 92%"),
    })
    support_evidence = _evidence(3, "Table 1", "membrane preparation", "porous stainless-steel discs")
    uf_evidence = _evidence(4, "", "UF average pore size", "36 nm")
    mf_evidence = _evidence(4, "", "MF average pore size", "180 nm")
    materials = [
        DraftMaterial(local_id="steel_support", name="porous stainless-steel disc", tags=["porous support"], ownership="focal_work", evidence=[support_evidence]),
        DraftMaterial(local_id="tio2_uf", name="suspension plasma-sprayed TiO2 ultrafiltration layer", formula="TiO2", tags=["ultrafiltration", "photocatalytic"], ownership="focal_work", evidence=[uf_evidence]),
        DraftMaterial(local_id="tio2_mf", name="suspension plasma-sprayed TiO2 microfiltration layer", formula="TiO2", tags=["microfiltration", "photocatalytic"], ownership="focal_work", evidence=[mf_evidence]),
    ]
    devices: list[DraftDevice] = []
    processes: list[DraftProcess] = []
    experiments: list[DraftExperiment] = []
    for variant in gold["variants"]:
        material_ref = "tio2_uf" if variant["type"] == "ultrafiltration" else "tio2_mf"
        table1 = _evidence(3, "Table 1", variant["name"], variant["spray_passes"])
        thickness_evidence = _evidence(7, "Table 2", variant["name"], f"{variant['thickness_um']:g}" if variant["thickness_um"] is not None else variant["spray_passes"])
        layer_count = 2 if "stacking" in variant["spray_passes"] else 1
        layers = [DraftDeviceLayer(sequence_index=0, role="support", material_ref="steel_support", evidence=[table1])]
        for layer_index in range(layer_count):
            layers.append(DraftDeviceLayer(
                sequence_index=layer_index + 1,
                role="membrane_body",
                material_ref=material_ref,
                thickness=_thickness(variant, thickness_evidence) if layer_index == 0 else None,
                deposition_method="suspension plasma spray",
                evidence=[table1],
            ))
        devices.append(DraftDevice(
            local_id=f"device_{variant['id']}", name=variant["name"], device_type="membrane_specimen",
            layer_stack=layers,
            configuration={
                "membrane_modality": "filtration", "architecture_type": "supported_porous_ceramic_membrane",
                "filtration_class": variant["type"], "spray_passes": variant["spray_passes"],
                "average_pore_size_nm": variant["pore_size_nm"], "stacked": layer_count == 2,
            },
            tags=[variant["type"], "filtration", "self-cleaning"], ownership="focal_work", evidence=[table1],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{variant['id']}",
            name=f"suspension plasma spray: {variant['spray_passes']} for {variant['name']}",
            family="suspension_plasma_spray",
            input_material_refs=["steel_support", material_ref],
            output_device_refs=[f"device_{variant['id']}"],
            equipment="suspension plasma spray torch",
            ownership="focal_work", evidence=[table1],
        ))
        filtration_outputs = []
        for particle_size, key in ((200, "frr_200"), (400, "frr_400")):
            raw = f"{variant[key]:g}"
            filtration_outputs.append(_measurement(
                "flux_recovery_ratio", raw, variant[key], "%",
                _evidence(10, "Table 4", variant["name"], raw),
                {
                    "scientific_type": "reported_derived_metric", "membrane_modality": "filtration",
                    "membrane_variant": variant["name"], "foulant": f"SiO2 {particle_size} nm",
                    "feed_concentration": "1 wt.%", "cleaning_method": "backwashing",
                    "transmembrane_pressure": 0.3, "pressure_unit": "bar",
                },
            ))
        experiments.append(DraftExperiment(
            local_id=f"silica_frr_{variant['id']}", experiment_type="dead_end_silica_filtration_fouling",
            device_refs=[f"device_{variant['id']}"], target="SiO2 fouling flux recovery",
            outputs=filtration_outputs,
            protocol="Dead-end vacuum filtration at about 0.3 bar followed by backwashing.",
            ownership="focal_work", evidence=[filtration_outputs[0].evidence[0]],
        ))

    device_by_name = {variant["name"]: f"device_{variant['id']}" for variant in gold["variants"]}
    for series in gold["self_cleaning_cycles"]:
        outputs = []
        all_values = ", ".join(f"{value:g}%" for value in series["values"])
        for cycle, value in enumerate(series["values"], start=1):
            raw = f"{value:g}"
            outputs.append(_measurement(
                "flux_recovery_ratio", raw, value, "%",
                _evidence(11, "", f"{series['variant']} self-cleaning cycles {all_values}", raw),
                {
                    "scientific_type": "reported_derived_metric", "membrane_modality": "filtration",
                    "membrane_variant": series["variant"], "foulant": "humic acid",
                    "cleaning_method": "visible-light photocatalytic cleaning", "cycle": cycle,
                },
            ))
        experiments.append(DraftExperiment(
            local_id=f"photocatalytic_cycles_{series['variant'].lower().replace('-', '_')}",
            experiment_type="visible_light_self_cleaning_cycles",
            device_refs=[device_by_name[series["variant"]]], target="humic-acid self-cleaning recyclability",
            outputs=outputs, protocol="Three humic-acid fouling and visible-light photocatalytic cleaning cycles.",
            ownership="focal_work", evidence=[outputs[0].evidence[0]],
        ))

    for item in gold["final_recovery"]:
        raw = f"{item['value']:g}"
        output = _measurement(
            "flux_recovery_ratio", raw, item["value"], "%",
            _evidence(12, "", "final flux recoveries after four hours and hydraulic cleaning", raw),
            {
                "scientific_type": "reported_derived_metric", "membrane_modality": "filtration",
                "membrane_variant": item["variant"], "foulant": "humic acid",
                "cleaning_method": "4 h visible-light photocatalysis followed by hydraulic cleaning",
                "stage": "post_cycle_3_final",
            },
        )
        experiments.append(DraftExperiment(
            local_id=f"final_recovery_{item['variant'].lower().replace('-', '_')}",
            experiment_type="photocatalytic_and_hydraulic_cleaning",
            device_refs=[device_by_name[item["variant"]]], target="final humic-acid flux recovery",
            outputs=[output], protocol="Four-hour photocatalytic cleaning followed by hydraulic cleaning.",
            ownership="focal_work", evidence=[output.evidence[0]],
        ))

    archive = assemble_archive(ExtractedDocument(
        source=_source(gold), materials=materials, devices=devices, processes=processes,
        experiments=experiments,
        domain_values={
            "case_id": gold["case_id"], "provider_invoked": False,
            "paper_types": ["membrane_fabrication", "filtration", "fouling_stability", "self_cleaning"],
            "modality_policy": "architecture, process, filtration, and self-cleaning remain separately represented",
        },
    ), domain="membranes", model="deterministic_mixed_modality_recovery")
    expected = (
        len(archive.materials), len(archive.devices), len(archive.processes),
        len(archive.experiments), len(_outputs(archive)), len(archive.calculations),
    )
    target = (
        gold["expected_materials"], gold["expected_devices"], gold["expected_processes"],
        gold["expected_experiments"], gold["expected_outputs"], 0,
    )
    if expected != target:
        quarantined = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
        raise ValueError(f"MEM-MIXED-H recovery count mismatch: {expected} != {target}; quarantine={quarantined}")
    return archive


def recover_closure_cases():
    review_archive, guarded_review, review_route = recover_review_f()
    negative_archive, negative_route_first, negative_route_second = recover_neg_g()
    return {
        "MEM-COMPUTE-E": recover_compute_e(),
        "MEM-REVIEW-F": review_archive,
        "MEM-NEG-G": negative_archive,
        "MEM-MIXED-H": recover_mixed_h(),
    }, {
        "review_guarded": guarded_review,
        "review_route": review_route,
        "negative_route_first": negative_route_first,
        "negative_route_second": negative_route_second,
    }
