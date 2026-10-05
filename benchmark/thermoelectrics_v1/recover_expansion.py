"""Deterministic recovery for TE-SERIES-B, TE-DERIVED-C, and TE-ANISO-D."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftProcess, DraftSource, ExtractedDocument

from benchmark.thermoelectrics_v1.recover_gold_a import (
    CASE_DIR,
    _cell_name,
    _load_xlsx_sheet,
    _series_digest,
    _source_data_evidence,
)


SERIES_PROPERTIES = {
    "electrical_conductivity": ("Figure 5a", "S/cm", "reported_measurement", None),
    "seebeck_coefficient": ("Figure 5b", "uV/K", "reported_measurement", None),
    "power_factor": ("Figure 5c", "uW/cm/K2", "reported_derived_metric", "author-reported S^2 sigma"),
}
SAMPLE_COLUMNS = {"x001": (1, 2), "x002": (3, 4), "x003": (5, 6)}
DERIVED_SPECS = {
    **{name: ("fig5_source_file", sheet, 5, 6, unit, scientific_type, basis)
       for name, (sheet, unit, scientific_type, basis) in SERIES_PROPERTIES.items()},
    "zt": ("fig5_source_file", "Figure 5d", 1, 2, "dimensionless", "reported_derived_metric", "author-reported S^2 sigma T / kappa_total"),
    "total_thermal_conductivity": ("fig4_source_file", "Figure 4e", 1, 3, "W/m/K", "reported_derived_metric", "author-reported thermal diffusivity times DSC heat capacity times density"),
}


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_lock(lock: dict) -> dict:
    for key, expected in lock.items():
        if key.endswith("_sha256"):
            file_key = key.removesuffix("_sha256")
            if file_key not in lock:
                continue
            if _sha256(CASE_DIR / lock[file_key]) != expected:
                raise ValueError(f"{lock['case_id']} locked checksum changed: {file_key}")
    gold_path = CASE_DIR / lock["gold_file"]
    if _sha256(gold_path) != lock["gold_sha256"]:
        raise ValueError(f"{lock['case_id']} frozen gold checksum changed")
    return _read(lock["gold_file"])


def _material(sample_id: str, spec: dict, evidence: Evidence) -> DraftMaterial:
    return DraftMaterial(
        local_id=sample_id, name=spec["name"], formula=spec["formula"], composition=spec["composition"],
        elements=["Na", "Sn", "Se"], phase="polycrystalline SnSe",
        dopants=[{"element": "Na", "nominal_x": spec.get("nominal_x", 0.03), "carrier_type": "p-type"}],
        tags=["thermoelectric", "p-type", "purified", "SPS-processed"], ownership="focal_work", evidence=[evidence],
    )


def _material_evidence() -> Evidence:
    snippet = "Purified and untreated materials with the nominal compositions NaxSn0.995−xSe (x = 0.01–0.03) and SnSe as a reference were synthesized by reacting stoichiometric mixtures of proper starting reagents."
    return Evidence(page=8, section="Synthesis", source_type=SourceType.text, original_source_type="publisher_pdf", verbatim_match=True, text_snippet=snippet, locator="page=8;section=Synthesis", confidence=1.0)


def _source_measurement(property_name: str, temperature: float, value: float, unit: str, scientific_type: str, basis: str | None, orientation: str, evidence: Evidence, sample_id: str) -> Measurement:
    conditions = {
        "scientific_type": scientific_type, "data_kind": "temperature_series_point",
        "temperature": temperature, "temperature_unit": "K", "measurement_orientation": orientation,
        "sample_state": "purified polycrystalline", "carrier_type": "p-type", "sample_identity": sample_id,
    }
    if basis:
        conditions["derivation_basis"] = basis
    if property_name == "seebeck_coefficient":
        conditions.update({"seebeck_sign": "positive" if value > 0 else "negative" if value < 0 else "zero", "absolute_value": False})
    return Measurement(property=property_name, raw_value=str(value), value=value, unit=unit, qualifier="exact", method="publisher source-data workbook", conditions=conditions, evidence=[evidence])


def recover_series_b():
    lock = _read("source_lock_series_b.json")
    gold = _verify_lock(lock)
    workbook = CASE_DIR / lock["fig5_source_file"]
    evidence = _material_evidence()
    materials = [_material(sample_id, spec, evidence) for sample_id, spec in gold["samples"].items()]
    experiments = []
    recovered: dict[str, list[list[float]]] = {}
    for property_name, (sheet, unit, scientific_type, basis) in SERIES_PROPERTIES.items():
        cells = _load_xlsx_sheet(workbook, sheet)
        for sample_id, (temperature_column, value_column) in SAMPLE_COLUMNS.items():
            points = []
            outputs = []
            for row in range(2, 24):
                temperature = float(cells[_cell_name(temperature_column, row)])
                value = float(cells[_cell_name(value_column, row)])
                points.append([temperature, value])
                source_evidence = _source_data_evidence(
                    source_sha=lock["fig5_source_file_sha256"], workbook_name=workbook.name, sheet=sheet, row=row,
                    temperature_column=temperature_column, value_column=value_column, temperature=temperature, value=value, unit=unit,
                )
                outputs.append(_source_measurement(property_name, temperature, value, unit, scientific_type, basis, "parallel to SPS direction", source_evidence, sample_id))
            key = f"{sample_id}/{property_name}"
            expected = gold["series"][key]
            if len(points) != expected["count"] or _series_digest(points) != expected["sha256"] or not all(item in points for item in expected["sentinels"]):
                raise ValueError(f"TE-SERIES-B frozen series differs: {key}")
            recovered[key] = points
            experiments.append(DraftExperiment(
                local_id=f"{sample_id}_{property_name}", experiment_type="temperature_dependent_thermoelectric_transport",
                material_refs=[sample_id], target=property_name, outputs=outputs,
                protocol="Exact publisher source-data cells; no interpolation or shared-grid substitution.", ownership="focal_work", evidence=[outputs[0].evidence[0]],
            ))
    draft = ExtractedDocument(
        source=DraftSource(**gold["source"]), materials=materials,
        processes=[DraftProcess(local_id="shared_synthesis_sps", name="Solid-state synthesis, purification, and SPS densification", family="solid_state_synthesis_and_spark_plasma_sintering", output_material_refs=list(gold["samples"]), ownership="focal_work", evidence=[evidence])],
        experiments=experiments,
        domain_values={"case_id": gold["case_id"], "provider_invoked": False, "recovery_method": "locked_publisher_workbook_cells_v1", "grid_policy": "per-sample exact temperatures; no interpolation"},
    )
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_source_data_recovery"), recovered


def recover_derived_c():
    lock = _read("source_lock_derived_c.json")
    gold = _verify_lock(lock)
    evidence = _material_evidence()
    material = _material("x003", gold["material"] | {"nominal_x": 0.03}, evidence)
    experiments = []
    recovered: dict[str, list[list[float]]] = {}
    for property_name, (file_key, sheet, temperature_column, value_column, unit, scientific_type, basis) in DERIVED_SPECS.items():
        workbook = CASE_DIR / lock[file_key]
        cells = _load_xlsx_sheet(workbook, sheet)
        points = []
        outputs = []
        for row in range(2, 100):
            temperature = cells.get(_cell_name(temperature_column, row))
            value = cells.get(_cell_name(value_column, row))
            if not isinstance(temperature, (int, float)) or not isinstance(value, (int, float)):
                continue
            pair = [float(temperature), float(value)]
            points.append(pair)
            source_evidence = _source_data_evidence(source_sha=lock[f"{file_key}_sha256"], workbook_name=workbook.name, sheet=sheet, row=row, temperature_column=temperature_column, value_column=value_column, temperature=pair[0], value=pair[1], unit=unit)
            outputs.append(_source_measurement(property_name, pair[0], pair[1], unit, scientific_type, basis, "parallel to SPS direction", source_evidence, "x003"))
        expected = gold["series"][property_name]
        if len(points) != expected["count"] or _series_digest(points) != expected["sha256"]:
            raise ValueError(f"TE-DERIVED-C frozen series differs: {property_name}")
        recovered[property_name] = points
        experiments.append(DraftExperiment(local_id=f"x003_{property_name}", experiment_type="temperature_dependent_thermoelectric_transport", material_refs=["x003"], target=property_name, outputs=outputs, protocol="Exact publisher source-data cells; reported derived metrics remain author-reported.", ownership="focal_work", evidence=[outputs[0].evidence[0]]))
    sigma = recovered["electrical_conductivity"]
    seebeck = recovered["seebeck_coefficient"]
    reported_pf = recovered["power_factor"]
    if not all(a[0] == b[0] == c[0] for a, b, c in zip(sigma, seebeck, reported_pf, strict=True)):
        raise ValueError("TE-DERIVED-C primitive and PF temperature rows do not align")
    relative_errors = [abs((s[1] ** 2 * e[1] * 1e-6) - pf[1]) / pf[1] for e, s, pf in zip(sigma, seebeck, reported_pf, strict=True)]
    validation = {"formula": "PF = S^2 sigma", "points": len(relative_errors), "max_relative_error": max(relative_errors), "canonical_measurements_created": 0, "status": "validation_only_noncanonical"}
    if validation["max_relative_error"] > gold["formula_validation"]["max_relative_error"]:
        raise ValueError("TE-DERIVED-C PF formula validation exceeds frozen rounding tolerance")
    draft = ExtractedDocument(source=DraftSource(**gold["source"]), materials=[material], experiments=experiments, domain_values={"case_id": gold["case_id"], "provider_invoked": False, "recovery_method": "locked_publisher_workbook_cells_v1", "synthex_formula_validation": validation, "silent_derivation": False})
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_source_data_recovery"), recovered, validation


def recover_aniso_d():
    lock = _read("source_lock_aniso_d.json")
    gold = _verify_lock(lock)
    article = CASE_DIR / lock["article_file"]
    supplementary = CASE_DIR / lock["supplementary_file"]
    with pymupdf.open(article) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError("TE-ANISO-D article page count changed")
        page_text = " ".join(document[4].get_text().replace("ﬁ", "fi").split())
        required = ("c-axis is 1.6 W m−1 K−1 at 300 K", "ab-plane (2.3 W m−1 K−1 at 300 K)")
        if not all(item in page_text for item in required):
            raise ValueError("TE-ANISO-D exact directional statement changed")
    with pymupdf.open(supplementary) as document:
        if len(document) != lock["supplementary_page_count"]:
            raise ValueError("TE-ANISO-D supplementary page count changed")
    snippet = "the κL along c-axis is 1.6 W m−1 K−1 at 300 K, which is about 30% lower than that in ab-plane (2.3 W m−1 K−1 at 300 K)"
    material_evidence = Evidence(page=5, section="TE properties of single-crystal Mg3Sb2", source_type=SourceType.text, original_source_type="publisher_pdf", verbatim_match=True, text_snippet="single-crystal Mg3Sb2", locator="page=5;Figure 4 discussion", confidence=1.0)
    material = DraftMaterial(local_id="ag_mg3sb2", name=gold["material"]["name"], formula=gold["material"]["formula"], composition=gold["material"]["composition"], elements=["Mg", "Sb"], phase="single-crystal Mg3Sb2", dopants=[{"element": "Ag", "amount": "not quantified in exact prose statement", "carrier_type": "p-type"}], tags=["thermoelectric", "p-type", "single crystal", "anisotropic"], ownership="focal_work", evidence=[material_evidence])
    outputs = []
    for item in gold["measurements"]:
        evidence = Evidence(page=5, section="TE properties of single-crystal Mg3Sb2", source_type=SourceType.text, original_source_type="publisher_pdf", verbatim_match=True, text_snippet=f"{snippet}; exact value {item['value']}", locator=f"page=5;Figure 4b discussion;orientation={item['orientation']}", confidence=1.0)
        outputs.append(Measurement(property=item["property"], raw_value=str(item["value"]), value=item["value"], unit=item["unit"], qualifier="exact", method="four-probe steady-state; electronic component subtracted with Wiedemann-Franz law", conditions={"scientific_type": item["scientific_type"], "data_kind": "orientation_specific_scalar", "temperature": item["temperature"], "temperature_unit": "K", "measurement_orientation": item["orientation"], "carrier_type": "p-type", "derivation_basis": "author-reported kappa_total minus Wiedemann-Franz electronic thermal conductivity"}, evidence=[evidence]))
    draft = ExtractedDocument(source=DraftSource(**gold["source"]), materials=[material], experiments=[DraftExperiment(local_id="directional_kappa_l", experiment_type="orientation_dependent_thermal_transport", material_refs=["ag_mg3sb2"], target="lattice_thermal_conductivity", outputs=outputs, protocol="Directions are explicit source identities and are neither inferred nor averaged.", ownership="focal_work", evidence=[item.evidence[0] for item in outputs])], domain_values={"case_id": gold["case_id"], "provider_invoked": False, "recovery_method": "locked_exact_publisher_prose_v1", "orientation_policy": "explicit_only_no_inference_no_averaging", "plot_only_values_excluded": True})
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_exact_prose_recovery"), outputs
