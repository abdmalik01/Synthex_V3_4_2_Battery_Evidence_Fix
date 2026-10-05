"""Deterministic recovery for the locked TE-GOLD-A publisher source data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)


CASE_DIR = Path(__file__).resolve().parent

SERIES_SPECS = {
    "electrical_conductivity": {
        "file_key": "fig5_source_file", "sheet": "Figure 5a", "temperature_column": 5,
        "value_column": 6, "unit": "S/cm", "scientific_type": "reported_measurement",
        "derivation_basis": None,
    },
    "seebeck_coefficient": {
        "file_key": "fig5_source_file", "sheet": "Figure 5b", "temperature_column": 5,
        "value_column": 6, "unit": "uV/K", "scientific_type": "reported_measurement",
        "derivation_basis": None,
    },
    "power_factor": {
        "file_key": "fig5_source_file", "sheet": "Figure 5c", "temperature_column": 5,
        "value_column": 6, "unit": "uW/cm/K2", "scientific_type": "reported_derived_metric",
        "derivation_basis": "author-reported S^2 sigma",
    },
    "zt": {
        "file_key": "fig5_source_file", "sheet": "Figure 5d", "temperature_column": 1,
        "value_column": 2, "unit": "dimensionless", "scientific_type": "reported_derived_metric",
        "derivation_basis": "author-reported S^2 sigma T / kappa_total",
    },
    "lattice_thermal_conductivity": {
        "file_key": "fig4_source_file", "sheet": "Figure 4d", "temperature_column": 9,
        "value_column": 10, "unit": "W/m/K", "scientific_type": "reported_derived_metric",
        "derivation_basis": "author-reported kappa_total minus Wiedemann-Franz kappa_electronic",
    },
    "total_thermal_conductivity": {
        "file_key": "fig4_source_file", "sheet": "Figure 4e", "temperature_column": 1,
        "value_column": 3, "unit": "W/m/K", "scientific_type": "reported_derived_metric",
        "derivation_basis": "author-reported thermal diffusivity times DSC heat capacity times density",
    },
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _series_digest(points: list[list[float]]) -> str:
    payload = json.dumps(points, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cell_name(column: int, row: int) -> str:
    letters = ""
    value = column
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def _load_xlsx_sheet(path: Path, sheet_name: str) -> dict[str, float | str]:
    """Read scalar XLSX cells with the standard library only."""
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(path) as package:
        workbook = ET.fromstring(package.read("xl/workbook.xml"))
        relationships = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall(f"{{{package_rel_ns}}}Relationship")
        }
        target = None
        for sheet in workbook.findall(f".//{{{main_ns}}}sheet"):
            if sheet.attrib.get("name") == sheet_name:
                target = targets[sheet.attrib[f"{{{rel_ns}}}id"]]
                break
        if target is None:
            raise ValueError(f"Missing worksheet {sheet_name!r} in {path.name}")
        sheet_path = "xl/" + target.lstrip("/").removeprefix("xl/")
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in package.namelist():
            shared_root = ET.fromstring(package.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(f".//{{{main_ns}}}t"))
                for item in shared_root.findall(f"{{{main_ns}}}si")
            ]
        root = ET.fromstring(package.read(sheet_path))
        cells: dict[str, float | str] = {}
        for cell in root.findall(f".//{{{main_ns}}}c"):
            reference = cell.attrib.get("r")
            value_node = cell.find(f"{{{main_ns}}}v")
            if not reference or value_node is None or value_node.text is None:
                continue
            raw = value_node.text
            if cell.attrib.get("t") == "s":
                cells[reference] = shared_strings[int(raw)]
            else:
                try:
                    cells[reference] = float(raw)
                except ValueError:
                    cells[reference] = raw
        return cells


def _source_data_evidence(
    *, source_sha: str, workbook_name: str, sheet: str, row: int,
    temperature_column: int, value_column: int, temperature: float, value: float, unit: str,
) -> Evidence:
    temperature_cell = _cell_name(temperature_column, row)
    value_cell = _cell_name(value_column, row)
    raw = str(value)
    snippet = f"{sheet}!{temperature_cell}={temperature} K; {sheet}!{value_cell}={raw} {unit}"
    return Evidence(
        source_type=SourceType.supplementary,
        original_source_type="official_source_data_workbook",
        verbatim_match=True,
        text_snippet=snippet,
        table_id=stable_id("tbl", source_sha, sheet),
        locator=f"workbook={workbook_name};sheet={sheet};temperature_cell={temperature_cell};value_cell={value_cell}",
        confidence=1.0,
    )


def _article_evidence(page: int, section: str, snippet: str) -> Evidence:
    return Evidence(
        page=page, section=section, source_type=SourceType.text,
        original_source_type="publisher_pdf", verbatim_match=True,
        text_snippet=snippet, locator=f"page={page};section={section}", confidence=1.0,
    )


def _measurement(property_name: str, point: dict, spec: dict) -> Measurement:
    value = point["value"]
    conditions = {
        "scientific_type": spec["scientific_type"],
        "data_kind": "temperature_series_point",
        "temperature": point["temperature"],
        "temperature_unit": "K",
        "measurement_orientation": "parallel to SPS direction",
        "sample_state": "purified polycrystalline",
        "carrier_type": "p-type",
    }
    if spec["derivation_basis"]:
        conditions["derivation_basis"] = spec["derivation_basis"]
    if property_name == "seebeck_coefficient":
        conditions.update({
            "seebeck_sign": "positive" if value > 0 else "negative" if value < 0 else "zero",
            "absolute_value": False,
        })
    if property_name == "zt":
        conditions["relative_uncertainty_percent"] = 10.0
    return Measurement(
        property=property_name, raw_value=str(value), value=value, unit=spec["unit"],
        qualifier="exact", method="publisher source-data workbook", conditions=conditions,
        evidence=[point["evidence"]],
    )


def _process_parameter(property_name: str, raw: str, value: float, unit: str, evidence: Evidence) -> Measurement:
    return Measurement(
        property=property_name, raw_value=raw, value=value, unit=unit, qualifier="exact",
        conditions={"scientific_type": "reported_process_parameter", "data_kind": "scalar"},
        evidence=[evidence.model_copy(update={"text_snippet": f"{evidence.text_snippet} {raw}"})],
    )


def _recover_series(lock: dict, gold: dict) -> dict[str, list[dict]]:
    recovered: dict[str, list[dict]] = {}
    for property_name, spec in SERIES_SPECS.items():
        source_path = CASE_DIR / lock[spec["file_key"]]
        cells = _load_xlsx_sheet(source_path, spec["sheet"])
        points = []
        pairs = []
        for row_number in range(2, 10002):
            temperature = cells.get(_cell_name(spec["temperature_column"], row_number))
            value = cells.get(_cell_name(spec["value_column"], row_number))
            if not isinstance(temperature, (int, float)) or not isinstance(value, (int, float)):
                if row_number > 100 and not any(key.endswith(str(row_number)) for key in cells):
                    break
                continue
            pair = [float(temperature), float(value)]
            pairs.append(pair)
            points.append({
                "temperature": pair[0], "value": pair[1],
                "evidence": _source_data_evidence(
                    source_sha=lock[f"{spec['file_key']}_sha256"],
                    workbook_name=source_path.name, sheet=spec["sheet"], row=row_number,
                    temperature_column=spec["temperature_column"], value_column=spec["value_column"],
                    temperature=pair[0], value=pair[1], unit=spec["unit"],
                ),
            })
        expected = gold["series"][property_name]
        if len(pairs) != expected["count"] or _series_digest(pairs) != expected["sha256"]:
            raise ValueError(f"TE-GOLD-A {property_name} series differs from frozen gold")
        if not all(sentinel in pairs for sentinel in expected["sentinels"]):
            raise ValueError(f"TE-GOLD-A {property_name} sentinel point is missing")
        recovered[property_name] = points
    return recovered


def supplementary_local_status(lock: dict, path: Path | None = None) -> str:
    """Report availability separately from the historical locked source identity.

    A missing publisher supplement is allowed in the link-only distribution;
    a supplied local copy must match the frozen bytes and page count.
    """
    path = path or CASE_DIR / lock["supplementary_file"]
    if not path.exists():
        return "not_available_locally"
    if _sha256(path) != lock["supplementary_file_sha256"]:
        raise ValueError("TE-GOLD-A locked source checksum changed: supplementary_file")
    with pymupdf.open(path) as supplementary:
        if len(supplementary) != lock["supplementary_page_count"]:
            raise ValueError("TE-GOLD-A supplementary page count differs from the source lock")
    return "verified_local"


def recover_gold_a():
    lock = _read(CASE_DIR / "source_lock.json")
    gold = _read(CASE_DIR / lock["gold_file"])
    for file_key in ("article_file", "fig4_source_file", "fig5_source_file"):
        path = CASE_DIR / lock[file_key]
        if _sha256(path) != lock[f"{file_key}_sha256"]:
            raise ValueError(f"TE-GOLD-A locked source checksum changed: {file_key}")
    if _sha256(CASE_DIR / lock["gold_file"]) != lock["gold_sha256"]:
        raise ValueError("TE-GOLD-A gold checksum differs from the source lock")
    supplementary_local_status(lock)
    with pymupdf.open(CASE_DIR / lock["article_file"]) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError("TE-GOLD-A article page count differs from the source lock")
        methods = " ".join(document[7].get_text().replace("ﬁ", "fi").split())
        required = (
            "NaxSn0.995", "1,223 K for 12 h", "773 K for 48 h", "613 K for 6 h",
            "783 K for 5 min", "50 MPa",
        )
        if not all(term in methods for term in required):
            raise ValueError("TE-GOLD-A methods context changed")
        figure_text = " ".join(document[4].get_text().replace("ﬁ", "fi").split())
        if "Polycrystalline samples were measured parallel to the SPS direction" not in figure_text:
            raise ValueError("TE-GOLD-A measurement orientation context changed")
    recovered = _recover_series(lock, gold)
    material_evidence = _article_evidence(
        8, "Synthesis",
        "Purified and untreated materials with the nominal compositions NaxSn0.995−xSe (x = 0.01–0.03) and SnSe as a reference were synthesized by reacting stoichiometric mixtures of proper starting reagents.",
    )
    process_text = (
        "They were loaded in carbon-coated and evacuated fused-silica tubes (roughly 10−4 Torr), and were heated at 1,223 K for 12 h, followed by quenching to ice water. "
        "The obtained ingots were further annealed at 773 K for 48 h and were cooled naturally to room temperature. "
        "They were pulverized by hand-grinding, and were subsequently purified at 613 K for 6 h under a 4% H2/96% Ar with a flow rate of 200 ml min−1. "
        "Powder samples in the die were densified at roughly 783 K for 5 min under an axial pressure of 50 MPa in a vacuum of roughly 1.4 × 10−2 Torr using SPS."
    )
    process_evidence = _article_evidence(8, "Synthesis and compacting powders", process_text)
    parameters = [
        _process_parameter("reaction_temperature", "1,223 K", 1223.0, "K", process_evidence),
        _process_parameter("reaction_time", "12 h", 12.0, "h", process_evidence),
        _process_parameter("annealing_temperature", "773 K", 773.0, "K", process_evidence),
        _process_parameter("annealing_time", "48 h", 48.0, "h", process_evidence),
        _process_parameter("purification_temperature", "613 K", 613.0, "K", process_evidence),
        _process_parameter("purification_time", "6 h", 6.0, "h", process_evidence),
        _process_parameter("sintering_temperature", "783 K", 783.0, "K", process_evidence),
        _process_parameter("sintering_time", "5 min", 5.0, "min", process_evidence),
        _process_parameter("sintering_pressure", "50 MPa", 50.0, "MPa", process_evidence),
        _process_parameter(
            "relative_density", "95.6%", 95.6, "%",
            Evidence(
                page=45, section="Supplementary Table 1", source_type=SourceType.supplementary,
                original_source_type="publisher_supplementary_pdf", verbatim_match=True,
                text_snippet="Na0.03Sn0.965Se 5.914 95.6%", table_id="Supplementary Table 1",
                locator="supplementary_page=45;row=Na0.03Sn0.965Se", confidence=1.0,
            ),
        ),
    ]
    material = DraftMaterial(
        local_id="na003_sn0965_se", name=gold["material"]["name"], formula=gold["material"]["formula"],
        composition=gold["material"]["composition"], elements=["Na", "Sn", "Se"],
        phase="polycrystalline SnSe (Pnma below phase transition)",
        dopants=[{"element": "Na", "nominal_x": 0.03, "carrier_type": "p-type"}],
        tags=["thermoelectric", "p-type", "purified", "SPS-processed"],
        ownership="focal_work", evidence=[material_evidence],
    )
    experiments = []
    for property_name, points in recovered.items():
        spec = SERIES_SPECS[property_name]
        outputs = [_measurement(property_name, point, spec) for point in points]
        experiments.append(DraftExperiment(
            local_id=f"series_{property_name}", experiment_type="temperature_dependent_thermoelectric_transport",
            material_refs=[material.local_id], target=property_name, outputs=outputs,
            protocol="Polycrystalline sample measured parallel to the SPS direction; exact values recovered from publisher source data.",
            ownership="focal_work", evidence=[outputs[0].evidence[0]],
        ))
    draft = ExtractedDocument(
        source=DraftSource(**gold["source"]), materials=[material],
        processes=[DraftProcess(
            local_id="synthesis_and_sps", name="Purification, synthesis, annealing, powder purification, and SPS densification",
            family="solid_state_synthesis_and_spark_plasma_sintering",
            output_material_refs=[material.local_id], parameters=parameters,
            atmosphere="Ar glovebox; H2/Ar powder purification; evacuated tube and SPS vacuum",
            equipment="SPS-211Lx", ownership="focal_work", evidence=[process_evidence],
        )],
        experiments=experiments,
        domain_values={
            "paper_types": ["thermoelectric_material_synthesis", "electrical_transport", "thermal_transport", "thermoelectric_performance"],
            "case_id": gold["case_id"], "recovery_method": "locked_publisher_workbook_cells_v1",
            "provider_invoked": False, "carrier_type": "p-type",
            "measurement_orientation": "parallel to SPS direction",
        },
    )
    archive = assemble_archive(draft, domain="thermoelectrics", model="deterministic_source_data_recovery")
    return archive, {name: [[point["temperature"], point["value"]] for point in points] for name, points in recovered.items()}
