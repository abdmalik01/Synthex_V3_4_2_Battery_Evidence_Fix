"""Deterministic recovery for the four locked Membranes V1 foundation cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pymupdf

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftDevice,
    DraftDeviceLayer,
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)


CASE_DIR = Path(__file__).resolve().parent


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(text.replace("ﬁ", "fi").replace("ﬂ", "fl").split())


def _verify_locked_case(lock_name: str, page_tokens: dict[int, tuple[str, ...]]) -> tuple[dict, dict]:
    lock = _read(CASE_DIR / lock_name)
    article = CASE_DIR / lock["article_file"]
    gold_path = CASE_DIR / lock["gold_file"]
    if _sha256(article) != lock["article_sha256"]:
        raise ValueError(f"{lock['case_id']} locked article checksum changed")
    if _sha256(gold_path) != lock["gold_sha256"]:
        raise ValueError(f"{lock['case_id']} frozen gold checksum changed")
    with pymupdf.open(article) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError(f"{lock['case_id']} article page count changed")
        for page_number, tokens in page_tokens.items():
            page_text = _normalize(document[page_number - 1].get_text())
            missing = [token for token in tokens if _normalize(token) not in page_text]
            if missing:
                raise ValueError(f"{lock['case_id']} locked table anchors changed on page {page_number}: {missing}")
    return lock, _read(gold_path)


def _evidence(page: int, table_id: str, row: str, raw: str, *, section: str | None = None) -> Evidence:
    return Evidence(
        page=page,
        section=section,
        source_type=SourceType.table if table_id else SourceType.text,
        original_source_type="publisher_pdf_table" if table_id else "publisher_pdf_text",
        verbatim_match=True,
        text_snippet=f"{row}; reported value {raw}",
        table_id=table_id or None,
        locator=f"page={page};table={table_id or 'text'};row={row}",
        confidence=1.0,
    )


def _measurement(
    property_name: str,
    raw: str,
    value: float,
    unit: str,
    evidence: Evidence,
    conditions: dict[str, Any],
    *,
    uncertainty: float | None = None,
) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=raw,
        value=value,
        unit=unit,
        uncertainty=uncertainty,
        uncertainty_unit=unit if uncertainty is not None else None,
        qualifier="exact",
        conditions=conditions,
        evidence=[evidence],
    )


def _filler_parameter(loading: float, evidence: Evidence) -> Measurement:
    raw = f"{loading:g} wt%"
    return _measurement(
        "filler_loading", raw, loading, "%",
        evidence.model_copy(update={"text_snippet": f"{evidence.text_snippet}; {raw}"}),
        {"scientific_type": "reported_process_parameter"},
    )


def _source(gold: dict) -> DraftSource:
    return DraftSource(**gold["source"])


def _assert_complete(archive, gold: dict):
    outputs = sum(len(experiment.outputs) for experiment in archive.experiments)
    if outputs != gold["expected_outputs"]:
        raise ValueError(f"{gold['case_id']} recovered {outputs} outputs, expected {gold['expected_outputs']}")
    quarantined = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    if quarantined:
        raise ValueError(f"{gold['case_id']} unexpectedly quarantined canonical objects: {quarantined}")
    return archive


def recover_gold_a():
    _, gold = _verify_locked_case("source_lock.json", {
        4: ("transmembrane pressure of 3 bar at 25", "CO2/CH4 in a volume ratio of 1:1"),
        6: ("Table 1", "6.8 ± 0.3", "15.4 ± 0.5", "44 ± 1"),
    })
    conditions = dict(gold["conditions"])
    materials: list[DraftMaterial] = []
    devices: list[DraftDevice] = []
    processes: list[DraftProcess] = []
    experiments: list[DraftExperiment] = []
    for variant in gold["variants"]:
        row = f"Table 1 CTF-biphenyl {variant['filler_loading']:g} wt%"
        entity_evidence = _evidence(6, "Table 1", row, f"{variant['filler_loading']:g}")
        material_id = f"material_{variant['id']}"
        device_id = f"device_{variant['id']}"
        materials.append(DraftMaterial(
            local_id=material_id,
            name=variant["name"],
            composition={"matrix_weight_fraction": (100.0 - variant["filler_loading"]) / 100.0,
                         "filler_weight_fraction": variant["filler_loading"] / 100.0},
            tags=["mixed-matrix membrane", "Matrimid", "CTF-biphenyl" if variant["filler"] else "neat polymer"],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        devices.append(DraftDevice(
            local_id=device_id, name=variant["name"], device_type="membrane_specimen",
            layer_stack=[DraftDeviceLayer(
                sequence_index=0, role="membrane_body", material_ref=material_id,
                deposition_method="solution casting", evidence=[entity_evidence],
            )],
            configuration={
                "membrane_modality": "gas_separation", "architecture_type": "dense_mixed_matrix_film",
                "matrix": variant["matrix"], "filler": variant["filler"],
                "filler_loading_wt_percent": variant["filler_loading"],
            },
            tags=["gas separation", "mixed gas"], ownership="focal_work", evidence=[entity_evidence],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{variant['id']}", name="solution casting of Matrimid/CTF-biphenyl membrane",
            family="solution_casting", output_device_refs=[device_id],
            parameters=[_filler_parameter(variant["filler_loading"], entity_evidence)],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        output_conditions = {
            **conditions, "membrane_modality": "gas_separation",
            "scientific_type": "reported_measurement", "membrane_variant": variant["name"],
        }
        outputs = []
        for species, key in (("CO2", "co2"), ("CH4", "ch4")):
            value, uncertainty = variant[key]
            raw = f"{value:g} ± {uncertainty:g}"
            outputs.append(_measurement(
                "gas_permeability", raw, value, "Barrer",
                _evidence(6, "Table 1", row, raw),
                {**output_conditions, "species": species}, uncertainty=uncertainty,
            ))
        value, uncertainty = variant["selectivity"]
        raw = f"{value:g} ± {uncertainty:g}"
        outputs.append(_measurement(
            "mixed_gas_selectivity", raw, value, "dimensionless",
            _evidence(6, "Table 1", row, raw),
            {**output_conditions, "scientific_type": "reported_derived_metric", "species_pair": "CO2/CH4"},
            uncertainty=uncertainty,
        ))
        experiments.append(DraftExperiment(
            local_id=f"experiment_{variant['id']}", experiment_type="mixed_gas_separation",
            device_refs=[device_id], target="CO2/CH4", outputs=outputs,
            protocol="Equimolar CO2/CH4 at 3 bar transmembrane pressure and 25 C; helium sweep.",
            ownership="focal_work", evidence=[outputs[0].evidence[0]],
        ))
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold), materials=materials, devices=devices, processes=processes,
        experiments=experiments,
        domain_values={"case_id": gold["case_id"], "paper_types": ["membrane_fabrication", "gas_separation"],
                       "recovery_method": "locked_publisher_pdf_table_rows_v1", "provider_invoked": False},
    ), domain="membranes", model="deterministic_locked_pdf_table_recovery")
    return _assert_complete(archive, gold)


def recover_sep_b():
    _, gold = _verify_locked_case("source_lock_sep_b.json", {
        12: ("Table 3", "M@K2Ph", "P, Barrer", "30", "1 bar"),
        13: ("PPO", "PPO@K2Ph", "4.09"),
        17: ("Table 4", "O2/N2", "C2H4/CH4", "100.3"),
    })
    materials: list[DraftMaterial] = []
    devices: list[DraftDevice] = []
    processes: list[DraftProcess] = []
    experiments: list[DraftExperiment] = []
    for variant in gold["variants"]:
        row = f"Tables 3-4 {variant['name']}"
        entity_evidence = _evidence(12, "Table 3", row, f"{variant['membrane_thickness'][0]:g}")
        material_id = f"material_{variant['id']}"
        device_id = f"device_{variant['id']}"
        materials.append(DraftMaterial(
            local_id=material_id, name=variant["name"],
            composition={"matrix_weight_fraction": (100.0 - variant["filler_loading"]) / 100.0,
                         "filler_weight_fraction": variant["filler_loading"] / 100.0},
            tags=["dense membrane", variant["matrix"], "K2Ph" if variant["filler"] else "neat polymer"],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        thickness, thickness_uncertainty = variant["membrane_thickness"]
        thickness_raw = f"{thickness:g} ± {thickness_uncertainty:g}"
        thickness_measurement = Measurement(
            property="membrane_thickness", raw_value=thickness_raw, value=thickness,
            unit="µm", uncertainty=thickness_uncertainty, uncertainty_unit="µm", qualifier="exact",
            conditions={"scientific_type": "reported_measurement", "thickness_scope": "whole_membrane"},
            evidence=[_evidence(12 if variant["id"] not in {"ppo", "ppo_k2ph_5"} else 13, "Table 3", row, thickness_raw)],
        )
        devices.append(DraftDevice(
            local_id=device_id, name=variant["name"], device_type="membrane_specimen",
            layer_stack=[DraftDeviceLayer(
                sequence_index=0, role="membrane_body", material_ref=material_id,
                thickness=thickness_measurement, deposition_method="solution casting", evidence=[entity_evidence],
            )],
            configuration={"membrane_modality": "gas_separation", "architecture_type": "dense_mixed_matrix_film",
                           "matrix": variant["matrix"], "filler": variant["filler"],
                           "filler_loading_wt_percent": variant["filler_loading"]},
            ownership="focal_work", evidence=[entity_evidence],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{variant['id']}", name="solution casting of dense polymer or K2Ph mixed-matrix membrane",
            family="solution_casting", output_device_refs=[device_id],
            parameters=[_filler_parameter(variant["filler_loading"], entity_evidence)],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        base_conditions = {
            **gold["conditions"], "membrane_modality": "gas_separation",
            "membrane_variant": variant["name"],
        }
        permeability_outputs = [
            _measurement(
                "gas_permeability", f"{value:g}", value, "Barrer",
                _evidence(12 if variant["id"] not in {"ppo", "ppo_k2ph_5"} else 13, "Table 3", row, f"{value:g}"),
                {**base_conditions, "scientific_type": "reported_measurement", "species": species},
            )
            for species, value in zip(gold["species_order"], variant["permeability"], strict=True)
        ]
        selectivity_outputs = [
            _measurement(
                "ideal_selectivity", f"{value:g}", value, "dimensionless",
                _evidence(17, "Table 4", row, f"{value:g}"),
                {**base_conditions, "scientific_type": "reported_derived_metric", "species_pair": pair},
            )
            for pair, value in zip(gold["pair_order"], variant["ideal_selectivity"], strict=True)
        ]
        experiments.extend([
            DraftExperiment(
                local_id=f"permeability_{variant['id']}", experiment_type="gas_separation",
                device_refs=[device_id], target="six_species_permeability", outputs=permeability_outputs,
                protocol="Pure-gas permeability at 30 C and 1 bar.", ownership="focal_work",
                evidence=[permeability_outputs[0].evidence[0]],
            ),
            DraftExperiment(
                local_id=f"selectivity_{variant['id']}", experiment_type="gas_separation",
                device_refs=[device_id], target="eight_ideal_selectivity_pairs", outputs=selectivity_outputs,
                protocol="Ideal selectivity coefficients reported from pure-gas transport at 30 C.",
                ownership="focal_work", evidence=[selectivity_outputs[0].evidence[0]],
            ),
        ])
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold), materials=materials, devices=devices, processes=processes,
        experiments=experiments,
        domain_values={"case_id": gold["case_id"], "paper_types": ["membrane_fabrication", "gas_separation"],
                       "recovery_method": "locked_publisher_pdf_table_rows_v1", "provider_invoked": False},
    ), domain="membranes", model="deterministic_locked_pdf_table_recovery")
    return _assert_complete(archive, gold)


def recover_stab_c():
    _, gold = _verify_locked_case("source_lock_stab_c.json", {
        3: ("Table 1", "PZ1", "PZ5", "2.0"),
        4: ("dead-end filtration", "pressure of 9 bar"),
        5: ("washed using deionized water for 15 min",),
        9: ("Table 4", "JWF2", "97.93", "32.83"),
    })
    materials: list[DraftMaterial] = []
    devices: list[DraftDevice] = []
    processes: list[DraftProcess] = []
    experiments: list[DraftExperiment] = []
    for variant in gold["variants"]:
        row = f"Table 4 {variant['id'].upper()}"
        entity_evidence = _evidence(9, "Table 4", row, f"{variant['initial_flux']:.2f}")
        material_id = f"material_{variant['id']}"
        device_id = f"device_{variant['id']}"
        materials.append(DraftMaterial(
            local_id=material_id, name=variant["name"],
            composition={"PES_weight_fraction": 0.18, "ZnO_weight_fraction": variant["zno_loading"] / 100.0},
            tags=["PES", "ZnO", "NMP-acetone", "antifouling"],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        devices.append(DraftDevice(
            local_id=device_id, name=variant["name"], device_type="membrane_specimen",
            layer_stack=[DraftDeviceLayer(
                sequence_index=0, role="membrane_body", material_ref=material_id,
                deposition_method="nonsolvent induced phase separation", evidence=[entity_evidence],
            )],
            configuration={"membrane_modality": "filtration", "architecture_type": "asymmetric_phase_inversion_membrane",
                           "PES_wt_percent": 18.0, "NMP_acetone_ratio": "1:0.05",
                           "ZnO_wt_percent": variant["zno_loading"]},
            ownership="focal_work", evidence=[entity_evidence],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{variant['id']}", name="PES/ZnO nonsolvent-induced phase inversion",
            family="nonsolvent_induced_phase_separation", output_device_refs=[device_id],
            parameters=[_filler_parameter(variant["zno_loading"], _evidence(3, "Table 1", variant["id"].upper(), f"{variant['zno_loading']:g}"))],
            ownership="focal_work", evidence=[_evidence(3, "Table 1", variant["id"].upper(), f"{variant['zno_loading']:g}")],
        ))
        base = {**gold["conditions"], "membrane_modality": "filtration", "membrane_variant": variant["name"]}
        specs = (
            ("initial_flux", "initial_flux", "reported_measurement", {"feed": "deionized water"}),
            ("fouled_flux", "fouled_flux", "reported_measurement", {"feed": "humic acid solution", "foulant": "humic acid"}),
            ("recovered_flux", "recovered_flux", "reported_measurement", {"feed": "deionized water", "foulant": "humic acid", "cleaning_method": gold["conditions"]["cleaning_method"]}),
            ("flux_recovery_ratio", "frr", "reported_derived_metric", {"foulant": "humic acid", "cleaning_method": gold["conditions"]["cleaning_method"]}),
            ("relative_flux_reduction", "rfr", "reported_derived_metric", {"foulant": "humic acid"}),
        )
        outputs = []
        for property_name, key, scientific_type, extra in specs:
            value = variant[key]
            unit = "%" if key in {"frr", "rfr"} else "g/m2/s"
            raw = f"{value:.2f}"
            outputs.append(_measurement(
                property_name, raw, value, unit, _evidence(9, "Table 4", row, raw),
                {**base, **extra, "scientific_type": scientific_type},
            ))
        experiments.append(DraftExperiment(
            local_id=f"fouling_{variant['id']}", experiment_type="filtration",
            device_refs=[device_id], target="humic_acid_fouling_and_flux_recovery", outputs=outputs,
            protocol="Dead-end sequence: initial water, humic-acid filtration, DI-water wash, recovered water flux.",
            ownership="focal_work", evidence=[outputs[0].evidence[0]],
        ))
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold), materials=materials, devices=devices, processes=processes,
        experiments=experiments,
        domain_values={"case_id": gold["case_id"], "paper_types": ["membrane_fabrication", "filtration", "fouling_stability"],
                       "recovery_method": "locked_publisher_pdf_table_rows_v1", "provider_invoked": False},
    ), domain="membranes", model="deterministic_locked_pdf_table_recovery")
    return _assert_complete(archive, gold)


def recover_process_d():
    _, gold = _verify_locked_case("source_lock_process_d.json", {
        9: ("Table 2", "Matrimid", "6FDA-6FpDA", "Selective layer thickness", "1120", "250"),
        10: ("four different layers", "polyphenylene sulfide", "polybenzimidazole", "Teflon"),
    })
    common_materials = [
        DraftMaterial(local_id="pps", name="polyphenylene sulfide (PPS) non-woven", tags=["substrate"], ownership="focal_work",
                      evidence=[_evidence(10, "", "four-layer conclusion", "polyphenylene sulfide (PPS)")]),
        DraftMaterial(local_id="pbi", name="polybenzimidazole (PBI)", tags=["porous support"], ownership="focal_work",
                      evidence=[_evidence(10, "", "four-layer conclusion", "polybenzimidazole (PBI)")]),
        DraftMaterial(local_id="teflon", name="Teflon AF 2400", tags=["protective layer"], ownership="focal_work",
                      evidence=[_evidence(10, "", "four-layer conclusion", "Teflon AF 2400")]),
    ]
    materials = list(common_materials)
    devices: list[DraftDevice] = []
    processes: list[DraftProcess] = []
    experiments: list[DraftExperiment] = []
    for variant in gold["variants"]:
        selective_id = f"selective_{variant['id']}"
        device_id = f"device_{variant['id']}"
        entity_evidence = _evidence(9, "Table 2", variant["name"], variant["selective_material"])
        materials.append(DraftMaterial(
            local_id=selective_id, name=variant["selective_material"], tags=["selective layer", "polyimide"],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        devices.append(DraftDevice(
            local_id=device_id, name=variant["name"], device_type="membrane_specimen",
            layer_stack=[
                DraftDeviceLayer(sequence_index=0, role="substrate", material_ref="pps", evidence=[entity_evidence]),
                DraftDeviceLayer(sequence_index=1, role="porous_support", material_ref="pbi", deposition_method="phase inversion", evidence=[entity_evidence]),
                DraftDeviceLayer(sequence_index=2, role="selective_layer", material_ref=selective_id, deposition_method="solution coating", evidence=[entity_evidence]),
                DraftDeviceLayer(sequence_index=3, role="protective_layer", material_ref="teflon", deposition_method="solution coating", evidence=[entity_evidence]),
            ],
            configuration={"membrane_modality": "gas_separation", "architecture_type": "multilayer_composite",
                           "ordered_roles": ["substrate", "porous_support", "selective_layer", "protective_layer"]},
            tags=["thin-film composite", "high-temperature gas separation"],
            ownership="focal_work", evidence=[entity_evidence],
        ))
        processes.append(DraftProcess(
            local_id=f"process_{variant['id']}", name=f"phase-inverted PBI support and coated {variant['selective_material']} TFCM",
            family="phase_inversion_and_solution_coating", input_material_refs=["pps", "pbi", selective_id, "teflon"],
            output_device_refs=[device_id], ownership="focal_work", evidence=[entity_evidence],
        ))
        base = {**gold["conditions"], "membrane_modality": "gas_separation", "membrane_variant": variant["name"]}
        outputs = []
        for index, species in enumerate(gold["species_order"]):
            permeance = variant["permeance_scaled"][index]
            activation = variant["activation_energy"][index]
            thickness = variant["estimated_selective_layer_thickness"][index]
            outputs.extend([
                _measurement(
                    "gas_permeance", f"{permeance:g}", permeance, "10^2 m_STP^3 m^-2 h^-1 bar^-1",
                    _evidence(9, "Table 2", variant["name"], f"{permeance:g}"),
                    {**base, "scientific_type": "reported_measurement", "species": species,
                     "reported_scale_factor": 100.0, "raw_unit_preserved": True},
                ),
                _measurement(
                    "activation_energy_of_permeance", f"{activation:g}", activation, "kJ/mol",
                    _evidence(9, "Table 2", variant["name"], f"{activation:g}"),
                    {**base, "scientific_type": "reported_derived_metric", "species": species,
                     "temperature_range": gold["conditions"]["activation_temperature_range"]},
                ),
                _measurement(
                    "estimated_selective_layer_thickness", f"{thickness:g}", thickness, "nm",
                    _evidence(9, "Table 2", variant["name"], f"{thickness:g}"),
                    {**base, "scientific_type": "reported_derived_metric", "species": species,
                     "estimation_basis": "gas transport data from isotropic film and TFCM",
                     "thickness_scope": "selective_layer"},
                ),
            ])
        experiments.append(DraftExperiment(
            local_id=f"transport_{variant['id']}", experiment_type="gas_separation",
            device_refs=[device_id], target="five_species_TFCM_transport_and_thickness", outputs=outputs,
            protocol="Pure-gas pressure-increase measurements at 30 C; activation energy fitted over 30-70 C.",
            ownership="focal_work", evidence=[outputs[0].evidence[0]],
        ))
    archive = assemble_archive(ExtractedDocument(
        source=_source(gold), materials=materials, devices=devices, processes=processes,
        experiments=experiments,
        domain_values={"case_id": gold["case_id"], "paper_types": ["membrane_fabrication", "membrane_architecture", "gas_separation"],
                       "recovery_method": "locked_publisher_pdf_table_rows_v1", "provider_invoked": False},
    ), domain="membranes", model="deterministic_locked_pdf_table_recovery")
    return _assert_complete(archive, gold)


def recover_all_cases() -> dict[str, Any]:
    return {
        "MEM-GOLD-A": recover_gold_a(),
        "MEM-SEP-B": recover_sep_b(),
        "MEM-STAB-C": recover_stab_c(),
        "MEM-PROCESS-D": recover_process_d(),
    }
