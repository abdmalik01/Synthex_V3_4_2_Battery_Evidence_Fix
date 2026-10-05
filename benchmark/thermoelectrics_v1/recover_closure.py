"""Deterministic recovery for the four Thermoelectrics V1 closure cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation,
    DraftExperiment,
    DraftMaterial,
    DraftSource,
    ExtractedDocument,
)
from synthex_platform.extraction.router import DomainRouter

from benchmark.thermoelectrics_v1.recover_gold_a import CASE_DIR


COMPUTE_PROPERTIES = {
    "carrier_concentration": ("1/cm3", None),
    "lattice_thermal_conductivity": ("W/m/K", "Slack formula from calculated elastic properties"),
    "seebeck_coefficient": ("uV/K", None),
    "electrical_conductivity": ("kS/m", None),
    "electronic_thermal_conductivity": ("W/m/K", "BoltzTraP2 electronic heat transport"),
    "zt": ("dimensionless", "calculated S^2 sigma T / (kappa_lattice + kappa_electronic)"),
}

COMPOSITIONS = {
    "AgBr": {"Ag": 1.0, "Br": 1.0},
    "AgI": {"Ag": 1.0, "I": 1.0},
    "Tl4O2": {"Tl": 4.0, "O": 2.0},
    "AgCl": {"Ag": 1.0, "Cl": 1.0},
    "Ag4S2": {"Ag": 4.0, "S": 2.0},
}


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_lock(name: str) -> tuple[dict, dict]:
    lock = _read(name)
    gold_path = CASE_DIR / lock["gold_file"]
    if _sha256(gold_path) != lock["gold_sha256"]:
        raise ValueError(f"{lock['case_id']} frozen gold checksum changed")
    for key, expected in lock.items():
        if not key.endswith("_sha256") or key == "gold_sha256":
            continue
        path_key = key.removesuffix("_sha256")
        if path_key not in lock and f"{path_key}_file" in lock:
            path_key = f"{path_key}_file"
        if _sha256(CASE_DIR / lock[path_key]) != expected:
            raise ValueError(f"{lock['case_id']} locked source checksum changed: {path_key}")
    return lock, _read(lock["gold_file"])


def _page_text(document, page_index: int) -> str:
    return " ".join(document[page_index].get_text().replace("ﬁ", "fi").replace("−", "-").split())


def _evidence(*, page: int, section: str, snippet: str, locator: str, source_type: SourceType = SourceType.text, table_id: str | None = None) -> Evidence:
    return Evidence(page=page, section=section, source_type=source_type, original_source_type="publisher_pdf", verbatim_match=True, text_snippet=snippet, table_id=table_id, locator=locator, confidence=1.0)


def recover_compute_e():
    lock, gold = _verify_lock("source_lock_compute_e.json")
    source_path = CASE_DIR / lock["source_file"]
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("TE-COMPUTE-E page count changed")
        method_text = _page_text(document, 4)
        table_text = _page_text(document, 9)
    required_method = ("(VASP) 5.4.1", "PBE", "BoltzTraP2", "0.04", "k-mesh")
    if not all(term in method_text for term in required_method):
        raise ValueError("TE-COMPUTE-E method context changed")
    if "Top 5 semiconductor materials sorted by ZT value at 300 K" not in table_text:
        raise ValueError("TE-COMPUTE-E Table 2 heading changed")

    materials = []
    calculations = []
    for row in gold["rows"]:
        row_values = [row[name] for name in COMPUTE_PROPERTIES if name != "carrier_concentration"]
        carrier_mantissa = f"{row['carrier_concentration']:.2e}".split("e", maxsplit=1)[0].rstrip("0").rstrip(".")
        if (
            row["material_id"] not in table_text
            or row["formula"] not in table_text
            or carrier_mantissa not in table_text
            or not all(str(value) in table_text for value in row_values)
        ):
            raise ValueError(f"TE-COMPUTE-E Table 2 row changed: {row['material_id']}")
        row_snippet = (
            f"Table 2 {row['material_id']} {row['formula']} N={row['carrier_concentration']} cm-3; "
            f"kappa_l={row['lattice_thermal_conductivity']} W/m/K; S={row['seebeck_coefficient']} uV/K; "
            f"sigma={row['electrical_conductivity']} kS/m; kappa_e={row['electronic_thermal_conductivity']} W/m/K; "
            f"ZT={row['zt']}; Type={row['carrier_type']}"
        )
        row_evidence = _evidence(page=10, section="High-Throughput Electrical Transport Properties", snippet=row_snippet, locator=f"page=10;Table 2;row={row['material_id']}", source_type=SourceType.table, table_id="Table 2")
        local_id = row["material_id"].replace("-", "_")
        materials.append(DraftMaterial(local_id=local_id, name=f"calculated {row['formula']}", formula=row["formula"], composition=COMPOSITIONS[row["formula"]], elements=list(COMPOSITIONS[row["formula"]]), tags=["thermoelectric", "computational", row["carrier_type"]], ownership="focal_work", evidence=[row_evidence]))
        outputs = []
        for property_name, (unit, basis) in COMPUTE_PROPERTIES.items():
            value = float(row[property_name])
            conditions = {
                "scientific_type": "calculated", "data_kind": "computational_table_value",
                "temperature": 300.0, "temperature_unit": "K", "measurement_orientation": "not_reported",
                "carrier_type": row["carrier_type"], "carrier_concentration": row["carrier_concentration"],
                "carrier_concentration_unit": "1/cm3", "material_database_id": row["material_id"],
            }
            if basis:
                conditions["derivation_basis"] = basis
            if property_name == "seebeck_coefficient":
                conditions.update({"seebeck_sign": "positive", "absolute_value": False})
            outputs.append(Measurement(property=property_name, raw_value=str(row[property_name]), value=value, unit=unit, qualifier="exact", method=gold["method"]["code"], conditions=conditions, evidence=[row_evidence]))
        calculations.append(DraftCalculation(local_id=f"calc_{local_id}", calculation_type="first_principles_boltzmann_thermoelectric_transport", material_refs=[local_id], code=gold["method"]["code"], method="high-throughput DFT, deformation-potential relaxation time, Slack lattice thermal conductivity, and BoltzTraP2 transport", functional=gold["method"]["functional"], model={"k_mesh_density": gold["method"]["k_mesh_density"], "relaxation_time_assumption": gold["method"]["relaxation_time"], "lattice_thermal_conductivity_model": gold["method"]["lattice_thermal_conductivity"], "orientation": "not_reported"}, outputs=outputs, ownership="focal_work", evidence=[row_evidence]))
    draft = ExtractedDocument(source=DraftSource(**gold["source"]), materials=materials, calculations=calculations, domain_values={"case_id": gold["case_id"], "provider_invoked": False, "source_table": "Table 2", "modality_policy": "calculated outputs only in CalculationRecord"})
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_computational_table_recovery")


def recover_review_f():
    lock, gold = _verify_lock("source_lock_review_f.json")
    source_path = CASE_DIR / lock["source_file"]
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("TE-REVIEW-F page count changed")
        first_page = _page_text(document, 0)
        table_page = _page_text(document, 8)
    publisher_signal = gold["publisher_review_signal"] in first_page
    author_signal = gold["author_self_description"] in first_page
    if not publisher_signal or not author_signal:
        raise ValueError("TE-REVIEW-F dual review detection failed")
    if "Selected thermoelectric materials with ZT > 1 in the last 3 years" not in table_page:
        raise ValueError("TE-REVIEW-F cited comparison table changed")
    materials = []
    experiments = []
    for index, (formula, temperature, zt) in enumerate(gold["cited_rows"], start=1):
        source_formula = formula if formula in table_page else formula.replace(",", ", ")
        if source_formula not in table_page or str(temperature).removesuffix(".0") not in table_page or f"{zt:.2f}" not in table_page:
            raise ValueError(f"TE-REVIEW-F cited row changed: {formula}")
        snippet = f"Table 2 cited prior work: {formula}; T={temperature} K; ZT={zt}"
        evidence = _evidence(page=9, section="Selected thermoelectric materials", snippet=snippet, locator=f"page=9;Table 2;row={index};reference=cited", source_type=SourceType.table, table_id="Table 2")
        local_id = f"cited_{index}"
        materials.append(DraftMaterial(local_id=local_id, name=formula, formula=formula, tags=["thermoelectric", "review_table", "cited_prior_work"], ownership="cited_prior_work", evidence=[evidence]))
        measurement = Measurement(property="zt", raw_value=str(zt), value=float(zt), unit="dimensionless", qualifier="exact", method="value reproduced by review from cited study", conditions={"scientific_type": "reported_derived_metric", "temperature": float(temperature), "temperature_unit": "K", "measurement_orientation": "not_reported", "derivation_basis": "cited study value reproduced in review comparison table", "ownership": "cited_prior_work"}, evidence=[evidence])
        experiments.append(DraftExperiment(local_id=f"cited_zt_{index}", experiment_type="review_comparison_table_entry", material_refs=[local_id], target="zt", outputs=[measurement], protocol="Cited literature value; not work performed by review authors.", ownership="cited_prior_work", evidence=[evidence]))
    draft = ExtractedDocument(source=DraftSource(**{key: value for key, value in gold["source"].items() if key != "article_type"}), materials=materials, experiments=experiments, domain_values={"case_id": gold["case_id"], "provider_invoked": False, "article_type": "Review", "review_detection": {"publisher_label": publisher_signal, "author_self_description": author_signal}, "cited_values_expected": gold["expected_cited_values"]})
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_review_containment"), gold["cited_rows"]


def recover_neg_g():
    lock, gold = _verify_lock("source_lock_neg_g.json")
    source_path = (CASE_DIR / lock["source_file"]).resolve()
    with pymupdf.open(source_path) as document:
        if len(document) != lock["page_count"]:
            raise ValueError("TE-NEG-G page count changed")
        text = "\n".join(page.get_text() for page in document)
    folded = text.casefold()
    if not all(term.casefold() in folded for term in gold["misleading_vocabulary"]):
        raise ValueError("TE-NEG-G misleading vocabulary changed")
    first = DomainRouter().route_text(text)
    second = DomainRouter().route_text(text)
    draft = ExtractedDocument(source=DraftSource(**{key: value for key, value in gold["source"].items() if key != "true_domain"}), domain_values={"case_id": gold["case_id"], "provider_invoked": False, "negative_control": True, "expected_route": gold["expected_route"]})
    archive = assemble_archive(draft, domain="thermoelectrics", model="negative_control_no_provider")
    return archive, first, second, text


def recover_mixed_h():
    lock, gold = _verify_lock("source_lock_mixed_h.json")
    with pymupdf.open(CASE_DIR / lock["article_file"]) as document:
        if len(document) != lock["article_page_count"]:
            raise ValueError("TE-MIXED-H article page count changed")
        page3 = _page_text(document, 2)
        page5 = _page_text(document, 4)
        page8 = _page_text(document, 7)
    with pymupdf.open(CASE_DIR / lock["supplementary_file"]) as document:
        if len(document) != lock["supplementary_page_count"]:
            raise ValueError("TE-MIXED-H supplementary page count changed")
        table2 = _page_text(document, 27)
    required = ("0.9me along", "0.11me along", "are estimated to be 0.9me and 0.16me")
    if not all(term in page3 for term in required):
        raise ValueError("TE-MIXED-H effective-mass statements changed")
    if "c-axis is 1.6 W m-1 K-1 at 300 K" not in page5 or "ab-plane (2.3 W m-1 K-1 at 300 K)" not in page5:
        raise ValueError("TE-MIXED-H directional thermal statement changed")
    if not all(term in page8 for term in ("Vienna ab initio Simulation Package", "Perdew", "Burke", "Ernzerhof", "400 eV", "k = 60/L")):
        raise ValueError("TE-MIXED-H calculation method changed")
    if not all(term in table2 for term in ("Supplementary Table 2", "Mg3Sb2", "0.90", "0.11")):
        raise ValueError("TE-MIXED-H supplementary calculation table changed")

    material_evidence = _evidence(page=3, section="Valence band anisotropy in Mg3Sb2", snippet="p-type Mg3Sb2 single crystal with a single anisotropic hole pocket", locator="page=3;section=Valence band anisotropy")
    material = DraftMaterial(local_id="mg3sb2", name=gold["material"]["name"], formula=gold["material"]["formula"], composition=gold["material"]["composition"], elements=["Mg", "Sb"], dopants=[{"element": "Ag", "nominal_x": 0.02, "carrier_type": "p-type"}], tags=["thermoelectric", "p-type", "single crystal", "mixed experimental computational"], ownership="focal_work", evidence=[material_evidence])
    effective_outputs = []
    thermal_outputs = []
    for item in gold["experimental"]:
        if item["property"] == "carrier_effective_mass":
            snippet = f"ARPES estimated {item['orientation']} carrier effective mass {item['value']} m_e at 20 K"
            evidence = _evidence(page=3, section="Valence band anisotropy in Mg3Sb2", snippet=snippet, locator=f"page=3;ARPES;orientation={item['orientation']}", source_type=SourceType.text)
            conditions = {"scientific_type": item["scientific_type"], "temperature": item["temperature"], "temperature_unit": "K", "measurement_orientation": item["orientation"], "carrier_type": "p-type", "data_kind": "experimental_band_curvature_estimate"}
            effective_outputs.append(Measurement(property=item["property"], raw_value=str(item["value"]), value=item["value"], unit=item["unit"], qualifier="exact", method=item["method"], conditions=conditions, evidence=[evidence]))
        else:
            snippet = f"lattice thermal conductivity along {item['orientation']} is {item['value']} W/m/K at 300 K"
            evidence = _evidence(page=5, section="TE properties of single-crystal Mg3Sb2", snippet=snippet, locator=f"page=5;Figure 4b discussion;orientation={item['orientation']}")
            conditions = {"scientific_type": item["scientific_type"], "temperature": item["temperature"], "temperature_unit": "K", "measurement_orientation": item["orientation"], "carrier_type": "p-type", "data_kind": "experimental_orientation_specific_scalar", "derivation_basis": "author-reported total thermal conductivity minus Wiedemann-Franz electronic component"}
            thermal_outputs.append(Measurement(property=item["property"], raw_value=str(item["value"]), value=item["value"], unit=item["unit"], qualifier="exact", method=item["method"], conditions=conditions, evidence=[evidence]))
    calculation_evidence = _evidence(page=28, section="Supplementary Table 2", snippet="Mg3Sb2 calculated m* Gamma-K 0.90 m_e; calculated m* Gamma-A 0.11 m_e", locator="supplementary_page=28;Table 2;row=Mg3Sb2", source_type=SourceType.computation, table_id="Supplementary Table 2")
    calculated_outputs = [Measurement(property=item["property"], raw_value=str(item["value"]), value=item["value"], unit=item["unit"], qualifier="exact", method="DFT band curvature", conditions={"scientific_type": "calculated", "measurement_orientation": item["orientation"], "carrier_type": "p-type", "data_kind": "first_principles_band_effective_mass"}, evidence=[calculation_evidence]) for item in gold["computational"]]
    experiments = [
        DraftExperiment(local_id="arpes_effective_mass", experiment_type="angle_resolved_photoemission_band_curvature", material_refs=["mg3sb2"], target="carrier_effective_mass", outputs=effective_outputs, protocol="ARPES at 20 K; effective masses estimated from measured band curvature.", ownership="focal_work", evidence=[item.evidence[0] for item in effective_outputs]),
        DraftExperiment(local_id="directional_lattice_kappa", experiment_type="orientation_dependent_thermal_transport", material_refs=["mg3sb2"], target="lattice_thermal_conductivity", outputs=thermal_outputs, protocol="Steady-state thermal transport; lattice component obtained by Wiedemann-Franz subtraction.", ownership="focal_work", evidence=[item.evidence[0] for item in thermal_outputs]),
    ]
    calculation = DraftCalculation(local_id="dft_effective_mass", calculation_type="first_principles_band_structure", material_refs=["mg3sb2"], code=gold["calculation_method"]["code"], method="projector augmented-wave DFT band-structure calculation", functional=gold["calculation_method"]["functional"], model={"energy_cutoff": gold["calculation_method"]["energy_cutoff"], "k_mesh": gold["calculation_method"]["k_mesh"], "force_convergence": gold["calculation_method"]["force_convergence"]}, outputs=calculated_outputs, ownership="focal_work", evidence=[calculation_evidence])
    draft = ExtractedDocument(source=DraftSource(**gold["source"]), materials=[material], experiments=experiments, calculations=[calculation], domain_values={"case_id": gold["case_id"], "provider_invoked": False, "modality_policy": "experimental and calculated values remain separate records", "same_property_cross_modality": "carrier_effective_mass"})
    return assemble_archive(draft, domain="thermoelectrics", model="deterministic_mixed_modality_recovery")
