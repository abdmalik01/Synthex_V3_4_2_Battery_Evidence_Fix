"""Deterministic recovery of the official PV-SPEC-B Fig. 3b EQE workbook."""

from __future__ import annotations

from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

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

from .case_common import CASE_DIR, assert_locked, canonical_digest, normalize_text, read_json, text_evidence


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(f".//{{{_MAIN}}}t")) for item in root]


def _sheet_cells(path: Path, sheet_name: str) -> dict[str, str | float | int | None]:
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relation_id = None
        for sheet in workbook.findall(f".//{{{_MAIN}}}sheet"):
            if sheet.attrib.get("name") == sheet_name:
                relation_id = sheet.attrib[f"{{{_DOC_REL}}}id"]
                break
        if relation_id is None:
            raise ValueError(f"Missing source-data worksheet: {sheet_name}")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            rel.attrib["Target"]
            for rel in relationships.findall(f"{{{_PKG_REL}}}Relationship")
            if rel.attrib["Id"] == relation_id
        )
        sheet_path = "xl/" + target.lstrip("/").removeprefix("xl/")
        root = ET.fromstring(archive.read(sheet_path))
        cells: dict[str, str | float | int | None] = {}
        for cell in root.findall(f".//{{{_MAIN}}}c"):
            ref = cell.attrib["r"]
            kind = cell.attrib.get("t")
            value_node = cell.find(f"{{{_MAIN}}}v")
            if kind == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(f".//{{{_MAIN}}}t"))
            elif value_node is None:
                value = None
            elif kind == "s":
                value = shared[int(value_node.text)]
            else:
                number = float(value_node.text)
                value = int(number) if number.is_integer() else number
            cells[ref] = value
        return cells


def _workbook_evidence(
    workbook_hash: str,
    label: str,
    row: int,
    column: str,
    raw_value: str,
) -> Evidence:
    table_id = stable_id("tbl", workbook_hash, "Fig. 3b")
    return Evidence(
        source_type="table",
        original_source_type="official_source_data_workbook",
        verbatim_match=True,
        text_snippet=raw_value,
        table_id=table_id,
        locator=(
            f"sheet=Fig. 3b;series={label};wavelength_cell=A{row};"
            f"value_cell={column}{row}"
        ),
    )


def recover_spec_b():
    lock = read_json("spec_b_source_lock.json")
    gold = read_json(lock["gold_file"])
    article = CASE_DIR / lock["article_file"]
    workbook = CASE_DIR / lock["source_data_file"]
    assert_locked(article, lock["article_sha256"], "PV-SPEC-B article")
    assert_locked(workbook, lock["source_data_sha256"], "PV-SPEC-B source data")
    assert_locked(CASE_DIR / lock["gold_file"], lock["gold_sha256"], "PV-SPEC-B gold")

    with pymupdf.open(article) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError("PV-SPEC-B article page count differs from source lock")
        device_text = normalize_text(document[3].get_text())
        methods_text = normalize_text(document[7].get_text())
    if not all(term in device_text for term in (
        "ITO", "PEDOT: PSS", "active layer", "PFN-Br", "Ag", "external quantum efficiency",
    )):
        raise ValueError("PV-SPEC-B device or Fig. 3 context changed")
    if not all(term in methods_text for term in ("external quantum efficiency", "IPCE", "QE-R")):
        raise ValueError("PV-SPEC-B EQE method context changed")

    cells = _sheet_cells(workbook, gold["measurement"]["workbook_sheet"])
    device_evidence = text_evidence(
        4,
        "indium tin oxide (ITO)/poly (3,4-ethylenedioxythiophene): poly (styrene sulfonate) (PEDOT: PSS)/active layer/poly[(9,9-bis(3’-((N,N-dimethyl)-N-ethylammonium)-propyl)−2,7-fluorene)-alt-2,7-(9,9-dioctylfluorene)] dibromide (PFN-Br)/Ag",
        section="Device performance of binary and ternary OSCs",
    )
    method_evidence = text_evidence(
        8,
        "The external quantum efficiency (EQE) was measured by a certified incident photon to electron conversion (IPCE) equipment (QE-R) from Enli Technology Co., Ltd.",
        section="Device fabrication and characterization",
    )

    materials = [
        DraftMaterial(local_id="ito", name="indium tin oxide", formula="ITO", tags=["transparent_electrode"], ownership="focal_work", evidence=[device_evidence]),
        DraftMaterial(local_id="pedot_pss", name="PEDOT:PSS", tags=["htl"], ownership="focal_work", evidence=[device_evidence]),
        DraftMaterial(local_id="pfn_br", name="PFN-Br", tags=["buffer"], ownership="focal_work", evidence=[device_evidence]),
        DraftMaterial(local_id="ag", name="silver electrode", formula="Ag", tags=["electrode"], ownership="focal_work", evidence=[device_evidence]),
    ]
    devices = []
    experiments = []
    recovered_series = []
    for expected in gold["series"]:
        variant = expected["variant"]
        label = expected["label"]
        column = expected["column"]
        absorber_ref = f"active_{variant}"
        device_ref = f"device_{variant}"
        materials.append(DraftMaterial(
            local_id=absorber_ref,
            name=f"{label} photoactive blend",
            tags=["absorber", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[device_evidence],
        ))
        layer_refs = [
            ("transparent_electrode", "ito"),
            ("htl", "pedot_pss"),
            ("absorber", absorber_ref),
            ("buffer", "pfn_br"),
            ("electrode", "ag"),
        ]
        devices.append(DraftDevice(
            local_id=device_ref,
            name=f"Organic solar cell — {label}",
            device_type="solar_cell",
            layer_stack=[
                DraftDeviceLayer(sequence_index=index, role=role, material_ref=material_ref, evidence=[device_evidence])
                for index, (role, material_ref) in enumerate(layer_refs)
            ],
            configuration={"architecture": "ITO/PEDOT:PSS/active layer/PFN-Br/Ag", "variant": variant, "active_layer": label},
            tags=["organic_solar_cell", "spectral_response", f"variant:{variant}"],
            ownership="focal_work",
            evidence=[device_evidence],
        ))

        points = []
        outputs = []
        for row in range(3, 84):
            wavelength = cells.get(f"A{row}")
            value = cells.get(f"{column}{row}")
            if value is None:
                continue
            if not isinstance(wavelength, (int, float)) or not isinstance(value, (int, float)):
                raise ValueError(f"Non-numeric PV-SPEC-B point at {column}{row}")
            point = {"wavelength_nm": wavelength, "eqe_percent": value}
            points.append(point)
            raw = str(value)
            outputs.append(Measurement(
                property="external_quantum_efficiency",
                raw_value=raw,
                value=float(value),
                unit="%",
                qualifier="exact",
                method=gold["measurement"]["method"],
                conditions={
                    "scientific_type": "reported_measurement",
                    "data_kind": "series_point",
                    "series_id": label,
                    "wavelength": float(wavelength),
                    "wavelength_unit": "nm",
                },
                evidence=[_workbook_evidence(lock["source_data_sha256"], label, row, column, raw)],
            ))
        if len(points) != expected["point_count"] or canonical_digest(points) != expected["points_sha256"]:
            raise ValueError(f"PV-SPEC-B {label} series differs from frozen gold")
        if points[0]["wavelength_nm"] != expected["wavelength_min_nm"] or points[-1]["wavelength_nm"] != expected["wavelength_max_nm"]:
            raise ValueError(f"PV-SPEC-B {label} wavelength range differs from frozen gold")
        recovered_series.append({"variant": variant, "label": label, "points": points})
        experiments.append(DraftExperiment(
            local_id=f"eqe_{variant}",
            experiment_type="external_quantum_efficiency_spectrum",
            device_refs=[device_ref],
            target="wavelength-dependent external quantum efficiency",
            outputs=outputs,
            protocol=gold["measurement"]["method"],
            ownership="focal_work",
            evidence=[method_evidence, outputs[0].evidence[0]],
        ))

    source = gold["source"]
    draft = ExtractedDocument(
        source=DraftSource(title=source["title"], doi=source["doi"], url=source["url"], year=source["year"], authors=source["authors"]),
        materials=materials,
        devices=devices,
        experiments=experiments,
        domain_values={
            "paper_types": ["device_architecture", "spectral_response"],
            "recovery_method": "official_source_data_xlsx_fig3b_cells_v1",
            "article_checksum": lock["article_sha256"],
            "source_data_checksum": lock["source_data_sha256"],
            "provider_invoked": False,
        },
    )
    return assemble_archive(draft, domain="photovoltaics", model="deterministic_source_data_recovery"), recovered_series
