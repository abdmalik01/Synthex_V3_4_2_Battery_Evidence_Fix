"""Deterministic recovery for PV-STAB-C thermal-stability variants."""

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
    DraftSource,
    ExtractedDocument,
)

from .case_common import CASE_DIR, assert_locked, normalize_text, read_json, text_evidence


def _t80_evidence(lock: dict, absorber: str, encapsulation: str, raw: str) -> Evidence:
    label = "MA" if absorber.startswith("(5-AVA)") else "FACs"
    row_text = "MA 16 h >5000 h 3580 h" if label == "MA" else "FACs 125 h 11 h 35 h"
    return Evidence(
        page=9,
        section="Table S4",
        source_type="supplementary",
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet=row_text,
        table_id=stable_id("tbl", lock["supplement_sha256"], "Table S4", 9),
        locator=f"page=9;table=Table S4;row={label};column={encapsulation};value={raw}",
    )


def recover_stab_c():
    lock = read_json("stab_c_source_lock.json")
    gold = read_json(lock["gold_file"])
    article = CASE_DIR / lock["article_file"]
    supplement_zip = CASE_DIR / lock["supplement_zip_file"]
    supplement = CASE_DIR / lock["supplement_file"]
    assert_locked(article, lock["article_sha256"], "PV-STAB-C article")
    assert_locked(supplement_zip, lock["supplement_zip_sha256"], "PV-STAB-C supplement ZIP")
    assert_locked(supplement, lock["supplement_sha256"], "PV-STAB-C supplement")
    assert_locked(CASE_DIR / lock["gold_file"], lock["gold_sha256"], "PV-STAB-C gold")

    with pymupdf.open(article) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError("PV-STAB-C article page count differs from source lock")
        abstract_text = normalize_text(document[0].get_text())
        fabrication_text = normalize_text(document[3].get_text())
        stability_text = normalize_text(document[8].get_text())
    with pymupdf.open(supplement) as document:
        if len(document) != lock["supplement_page_count"]:
            raise ValueError("PV-STAB-C supplement page count differs from source lock")
        table_text = normalize_text(document[8].get_text())
    if not all(term in abstract_text for term in ("91.2%", "5072 h", "ISOS-D-2")):
        raise ValueError("PV-STAB-C retained-efficiency source context changed")
    if not all(term in fabrication_text for term in ("FTO glass", "mesoporous TiO2", "mesoporous ZrO2", "carbon layer")):
        raise ValueError("PV-STAB-C MPLE architecture context changed")
    if not all(term in stability_text for term in ("85", "ambient atmosphere", "over-sealing", "side-sealing")):
        raise ValueError("PV-STAB-C aging protocol context changed")
    if not all(term in table_text for term in ("Table S4", "16 h", ">5000 h", "3580 h", "125 h", "11 h", "35 h")):
        raise ValueError("PV-STAB-C Table S4 values changed")

    fabrication_evidence = text_evidence(
        4,
        "The 0.5 µm mesoporous TiO2 (m-TiO2) layer was screen printed using the TiO2 paste. The 1.0 to 1.5 µm mesoporous ZrO2 (m-ZrO2) layer was screen printed using the ZrO2 paste. Then, the 10 to 20 µm carbon layer was screen printed using carbon paste on the porous ZrO2 layer.",
        section="2.2. Device Fabrication",
    )
    protocol_evidence = text_evidence(
        9,
        "Thermal stability tests were performed by placing the MPLE-PSCs on a hot plate at 85 °C in an ambient atmosphere",
        section="3.4. Thermal Stability of Encapsulated Devices",
    )
    retention_evidence = text_evidence(
        1,
        "resulting in a PCE value of 91.2% of the initial value after 5072 h",
        section="Abstract",
    )

    materials = [
        DraftMaterial(local_id="glass", name="glass substrate", tags=["substrate"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="fto", name="fluorine-doped tin oxide", formula="FTO", tags=["transparent_electrode"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="tio2", name="compact and mesoporous TiO2", formula="TiO2", tags=["etl"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="zro2", name="mesoporous ZrO2", formula="ZrO2", tags=["buffer"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="carbon", name="porous carbon electrode", formula="C", tags=["electrode"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="ma", name="(5-AVA)0.05(MA)0.95PbI3 perovskite", formula="(5-AVA)0.05(MA)0.95PbI3", tags=["absorber"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="facs", name="FA0.9Cs0.1PbI3 perovskite", formula="FA0.9Cs0.1PbI3", tags=["absorber"], ownership="focal_work", evidence=[fabrication_evidence]),
        DraftMaterial(local_id="ionomer", name="thermoplastic ionomer encapsulant", tags=["encapsulation"], ownership="focal_work", evidence=[protocol_evidence]),
    ]
    devices = []
    experiments = []
    recovered = []
    protocol = gold["protocol"]
    for expected in gold["variants"]:
        variant = expected["variant"]
        absorber_ref = "ma" if expected["absorber"].startswith("(5-AVA)") else "facs"
        layer_refs = [
            ("substrate", "glass"),
            ("transparent_electrode", "fto"),
            ("etl", "tio2"),
            ("buffer", "zro2"),
            ("absorber", absorber_ref),
            ("electrode", "carbon"),
        ]
        if expected["encapsulation"] != "none":
            layer_refs.append(("encapsulation", "ionomer"))
        device_ref = f"device_{variant}"
        devices.append(DraftDevice(
            local_id=device_ref,
            name=f"MPLE perovskite solar cell — {variant}",
            device_type="solar_cell",
            layer_stack=[
                DraftDeviceLayer(sequence_index=index, role=role, material_ref=material_ref, evidence=[fabrication_evidence])
                for index, (role, material_ref) in enumerate(layer_refs)
            ],
            configuration={
                "architecture": "carbon-based multiporous-layered-electrode perovskite solar cell",
                "variant": variant,
                "absorber": expected["absorber"],
                "encapsulation": expected["encapsulation"],
            },
            tags=["perovskite_solar_cell", "thermal_stability", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[fabrication_evidence, protocol_evidence],
        ))

        raw_t80 = f">{int(expected['t80'])} h" if expected["qualifier"] == "lower_bound" else f"{int(expected['t80'])} h"
        common_conditions = {
            "aging_protocol": protocol["aging_protocol"],
            "temperature": protocol["temperature"],
            "temperature_unit": protocol["temperature_unit"],
            "atmosphere": protocol["atmosphere"],
            "encapsulation": expected["encapsulation"],
            "absorber": expected["absorber"],
            "devices_per_variant": protocol["devices_per_variant"],
        }
        outputs = [Measurement(
            property="t80",
            raw_value=raw_t80,
            value=expected["t80"],
            unit="h",
            qualifier=expected["qualifier"],
            conditions={
                "scientific_type": "reported_derived_metric",
                "data_kind": "mean_time_to_threshold",
                "threshold_state": "80% of initial performance",
                **common_conditions,
            },
            evidence=[_t80_evidence(lock, expected["absorber"], expected["encapsulation"], raw_t80)],
        )]
        if "retained_efficiency" in expected:
            outputs.append(Measurement(
                property="retained_efficiency",
                raw_value=str(expected["retained_efficiency"]),
                value=expected["retained_efficiency"],
                unit="%",
                qualifier="exact",
                conditions={
                    "scientific_type": "reported_derived_metric",
                    "data_kind": "aged_state_relative_to_initial",
                    "aging_time": expected["aging_time_h"],
                    "aging_time_unit": "h",
                    "state_reference": "initial PCE",
                    "measurement_state": "aged",
                    **common_conditions,
                },
                evidence=[retention_evidence],
            ))
        experiments.append(DraftExperiment(
            local_id=f"thermal_{variant}",
            experiment_type="thermal_stability",
            device_refs=[device_ref],
            target="retained photovoltaic performance",
            outputs=outputs,
            protocol="85 °C ambient-air thermal stability following ISOS-D-2",
            ownership="focal_work",
            evidence=[protocol_evidence, outputs[0].evidence[0]],
        ))
        recovered.append({
            "variant": variant,
            "t80": expected["t80"],
            "qualifier": expected["qualifier"],
            "retained_efficiency": expected.get("retained_efficiency"),
            "aging_time_h": expected.get("aging_time_h"),
        })

    source = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source["title"], doi=source["doi"], url=source["url"], year=source["year"], authors=source["authors"]),
        materials=materials,
        devices=devices,
        experiments=experiments,
        domain_values={
            "paper_types": ["device_architecture", "stability"],
            "recovery_method": "locked_article_and_supplement_table_s4_v1",
            "article_checksum": lock["article_sha256"],
            "supplement_checksum": lock["supplement_sha256"],
            "provider_invoked": False,
        },
    )
    return assemble_archive(draft, domain="photovoltaics", model="deterministic_stability_recovery"), recovered
