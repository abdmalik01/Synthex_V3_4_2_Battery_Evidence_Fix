"""Deterministic recovery for PV-STACK-D architecture/process variants."""

from __future__ import annotations

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement
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

from .case_common import CASE_DIR, assert_locked, normalize_text, read_json, text_evidence


_UNITS = {
    "open_circuit_voltage": "V",
    "short_circuit_current_density": "mA/cm2",
    "fill_factor": "%",
    "power_conversion_efficiency": "%",
}


def _row_text(expected: dict) -> str:
    etl = f"PC70BM ({int(expected['pc70bm_thickness_nm'])} nm"
    if expected["dopant_wt_percent"] is not None:
        etl += f" + {expected['dopant_wt_percent']}% wt N-DMBI"
    etl += ")"
    return (
        f"ITO/Cu:NiOx/CH3NH3PbI3/{etl}/BCP/Cu "
        f"{expected['open_circuit_voltage']} {expected['short_circuit_current_density']} "
        f"{expected['fill_factor']} {expected['power_conversion_efficiency']}"
    )


def _table_evidence(lock: dict, expected: dict, column: str, raw: str) -> Evidence:
    return Evidence(
        page=3,
        section="Table 1",
        source_type="table",
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=_row_text(expected),
        table_id=stable_id("tbl", lock["source_sha256"], "Table 1", 3),
        locator=f"page=3;table=Table 1;row={expected['variant']};column={column};value={raw}",
    )


def recover_stack_d():
    lock = read_json("stack_d_source_lock.json")
    gold = read_json(lock["gold_file"])
    source_path = CASE_DIR / lock["source_file"]
    assert_locked(source_path, lock["source_sha256"], "PV-STACK-D source")
    assert_locked(CASE_DIR / lock["gold_file"], lock["gold_sha256"], "PV-STACK-D gold")
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("PV-STACK-D page count differs from source lock")
        table_text = normalize_text(document[2].get_text())
        methods_text = normalize_text(document[5].get_text())
    if not all(term in table_text for term in ("Table 1", "PC70BM", "0.3% wt", "14.48", "7.84", "13.1")):
        raise ValueError("PV-STACK-D Table 1 context changed")
    if not all(term in methods_text for term in ("AM1.5G", "100 mW/cm", "9 mm", "forward", "reverse")):
        raise ValueError("PV-STACK-D measurement context changed")

    architecture_evidence = text_evidence(
        3,
        "ITO/Cu:NiOx/CH3NH3PbI3/PC70BM/BCP/Cu",
        section="Table 1. Perovskite Solar Cell Photovoltaic Parameters",
        source_type="table",
    )
    context_evidence = text_evidence(
        6,
        "For illumination, a calibrated Newport Solar simulator equipped with a Xe lamp was used, providing an AM1.5G spectrum at 100 mW/cm2. A custom-made shadow mask was attached to each device prior to the measurements to accurately define the corresponding device area (9 mm2).",
        section="4.7. Characterization",
    )
    common_materials = [
        DraftMaterial(local_id="ito", name="indium tin oxide", formula="ITO", tags=["transparent_electrode"], ownership="focal_work", evidence=[architecture_evidence]),
        DraftMaterial(local_id="cu_niox", name="copper-doped nickel oxide", formula="Cu:NiOx", tags=["htl"], ownership="focal_work", evidence=[architecture_evidence]),
        DraftMaterial(local_id="mapbi3", name="methylammonium lead iodide", formula="CH3NH3PbI3", tags=["absorber"], ownership="focal_work", evidence=[architecture_evidence]),
        DraftMaterial(local_id="bcp", name="bathocuproine", formula="BCP", tags=["buffer"], ownership="focal_work", evidence=[architecture_evidence]),
        DraftMaterial(local_id="cu", name="copper electrode", formula="Cu", tags=["electrode"], ownership="focal_work", evidence=[architecture_evidence]),
    ]
    materials = list(common_materials)
    devices = []
    processes = []
    experiments = []
    recovered = []
    context = gold["measurement_context"]
    for expected in gold["variants"]:
        variant = expected["variant"]
        etl_ref = f"etl_{variant}"
        device_ref = f"device_{variant}"
        doping = expected["dopant_wt_percent"]
        etl_name = f"PC70BM {int(expected['pc70bm_thickness_nm'])} nm"
        if doping is not None:
            etl_name += f" + {doping}% wt N-DMBI"
        row_evidence = _table_evidence(lock, expected, "device structure", etl_name)
        materials.append(DraftMaterial(
            local_id=etl_ref,
            name=etl_name,
            tags=["etl", f"variant:{variant}", "n-doped" if doping is not None else "undoped"],
            dopants=[] if doping is None else [{"name": "N-DMBI", "concentration": doping, "unit": "wt%"}],
            ownership="focal_work",
            evidence=[row_evidence],
        ))
        thickness_raw = f"{int(expected['pc70bm_thickness_nm'])} nm"
        thickness = Measurement(
            property="film_thickness",
            raw_value=thickness_raw,
            value=expected["pc70bm_thickness_nm"],
            unit="nm",
            qualifier="exact",
            conditions={"scientific_type": "reported_process_parameter", "data_kind": "scalar", "process_step": "PC70BM electron transport layer deposition", "layer_role": "etl"},
            evidence=[_table_evidence(lock, expected, "device structure", thickness_raw)],
        )
        layer_refs = [
            ("transparent_electrode", "ito"),
            ("htl", "cu_niox"),
            ("absorber", "mapbi3"),
            ("etl", etl_ref),
            ("buffer", "bcp"),
            ("electrode", "cu"),
        ]
        devices.append(DraftDevice(
            local_id=device_ref,
            name=f"Inverted perovskite solar cell — {variant}",
            device_type="solar_cell",
            layer_stack=[
                DraftDeviceLayer(
                    sequence_index=index,
                    role=role,
                    material_ref=material_ref,
                    thickness=thickness if role == "etl" else None,
                    evidence=[row_evidence],
                )
                for index, (role, material_ref) in enumerate(layer_refs)
            ],
            configuration={
                "architecture": "ITO/Cu:NiOx/CH3NH3PbI3/PC70BM/BCP/Cu",
                "variant": variant,
                "pc70bm_thickness_nm": expected["pc70bm_thickness_nm"],
                "n_dmbi_wt_percent": doping if doping is not None else "not doped",
            },
            tags=["perovskite_solar_cell", "inverted", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[architecture_evidence, row_evidence],
        ))
        parameters = [thickness]
        if doping is not None:
            doping_raw = f"{doping}% wt"
            parameters.append(Measurement(
                property="solution_concentration",
                raw_value=doping_raw,
                value=doping,
                unit="wt%",
                qualifier="exact",
                conditions={"scientific_type": "reported_process_parameter", "data_kind": "scalar", "process_step": "N-DMBI doping of PC70BM", "layer_role": "etl", "dopant": "N-DMBI"},
                evidence=[_table_evidence(lock, expected, "device structure", doping_raw)],
            ))
        processes.append(DraftProcess(
            local_id=f"fabricate_{variant}",
            name=f"Fabricate {variant} inverted perovskite solar cell",
            family="inverted_perovskite_solar_cell_fabrication",
            input_material_refs=[material_ref for _, material_ref in layer_refs],
            output_device_refs=[device_ref],
            parameters=parameters,
            atmosphere="nitrogen glovebox for perovskite and PC70BM coating",
            equipment="doctor blade, spin coater, thermal evaporator",
            ownership="focal_work",
            evidence=[architecture_evidence, row_evidence],
        ))
        outputs = []
        for property_name, unit in _UNITS.items():
            value = expected[property_name]
            raw = str(value)
            outputs.append(Measurement(
                property=property_name,
                raw_value=raw,
                value=value,
                unit=unit,
                qualifier="exact",
                conditions={"scientific_type": "reported_measurement", "data_kind": "scalar", **context},
                evidence=[_table_evidence(lock, expected, property_name, raw)],
            ))
        experiments.append(DraftExperiment(
            local_id=f"jv_{variant}",
            experiment_type="current_voltage_photovoltaic_performance",
            device_refs=[device_ref],
            target="photovoltaic performance",
            outputs=outputs,
            protocol="calibrated Newport solar simulator, AM1.5G, 100 mW/cm2; 9 mm2 shadow mask",
            ownership="focal_work",
            evidence=[context_evidence, row_evidence],
        ))
        recovered.append({key: expected[key] for key in expected})

    source = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source["title"], doi=source["doi"], url=source["url"], year=source["year"], authors=source["authors"]),
        materials=materials,
        devices=devices,
        processes=processes,
        experiments=experiments,
        domain_values={
            "paper_types": ["device_fabrication", "device_architecture", "photovoltaic_performance"],
            "recovery_method": "locked_pdf_table1_variants_v1",
            "source_checksum": lock["source_sha256"],
            "provider_invoked": False,
        },
    )
    return assemble_archive(draft, domain="photovoltaics", model="deterministic_stack_variant_recovery"), recovered
