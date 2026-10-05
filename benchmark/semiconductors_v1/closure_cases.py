"""Offline, source-locked semiconductor compute/review/control/mixed recovery.

No gold file is read by the recovery functions. Published PDF text is the only
source of numerical outputs; gold is independently compared in closure_audit.
"""

from __future__ import annotations

import re

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftCalculation, DraftDevice, DraftDeviceLayer, DraftExperiment,
    DraftMaterial, DraftProcess, DraftSource, ExtractedDocument,
)
from synthex_platform.extraction.router import DomainRouter

from .source_tables import page_text, source_lock


def _source(case: str) -> DraftSource:
    lock = source_lock(case)
    return DraftSource(title=lock["source_title"], doi=lock["doi"], url=lock["article_url"])


def _line(case: str, page: int, needle: str, following: int = 0) -> str:
    lines = (page_text(case, page)).splitlines()
    index = next((i for i, line in enumerate(lines) if needle in line), None)
    if index is None:
        raise ValueError(f"Missing source anchor: {case} page {page}: {needle}")
    return "\n".join(line.strip() for line in lines[index:index + following + 1])


def _ev(case: str, page: int, snippet: str, *, kind: SourceType = SourceType.text,
        locator: str | None = None, table_id: str | None = None) -> Evidence:
    if snippet not in page_text(case, page):
        raise ValueError(f"Non-verbatim evidence: {case} page {page}: {snippet!r}")
    return Evidence(page=page, source_type=kind,
                    original_source_type="publisher_pdf_table" if kind == SourceType.table else "publisher_pdf_text",
                    verbatim_match=True, text_snippet=snippet, locator=locator or f"page={page}", table_id=table_id)


def _measurement(prop: str, raw: str, unit: str, ev: Evidence, sample: str,
                 *, calculated: bool = False, method: str | None = None,
                 conditions: dict | None = None, normalized: tuple[float, str] | None = None) -> Measurement:
    return Measurement(property=prop, raw_value=raw, value=float(raw), unit=unit,
                       normalized_value=normalized[0] if normalized else None,
                       normalized_unit=normalized[1] if normalized else None,
                       qualifier="exact", method=method,
                       conditions={"scientific_type": "calculated" if calculated else "reported_measurement",
                                   "sample_label": sample, **(conditions or {})}, evidence=[ev])


def compute_e_rows() -> list[dict]:
    text = page_text("SEM-COMPUTE-E", 5)
    header = "SOC PBE HSE03 HSE06 G0W0 GW0 GW HSE06-G0W0"
    if header not in text or "Table 1." not in text:
        raise ValueError("SEM-COMPUTE-E Table 1 header missing")
    keys = header.split()[1:]
    rows = []
    for label in ("Without", "With"):
        line = next((part for part in text.splitlines() if part.startswith(label + " ")), None)
        if line is None:
            raise ValueError(f"SEM-COMPUTE-E missing SOC row: {label}")
        cells = line.split()[1:]
        if len(cells) != len(keys):
            raise ValueError(f"SEM-COMPUTE-E ambiguous row: {line}")
        rows.append({"soc": label.casefold(), "values": {
            key: None if cell in {"–", "-", "—"} else float(cell)
            for key, cell in zip(keys, cells)}, "raw_cells": dict(zip(keys, cells)), "source_line": line})
    return rows


def recover_compute_e():
    case = "SEM-COMPUTE-E"
    draft = ExtractedDocument(source=_source(case))
    title_ev = _ev(case, 1, _line(case, 1, "AlSb monolayer"))
    draft.materials.append(DraftMaterial(local_id="alsb_monolayer", name="AlSb monolayer",
                                         formula="AlSb", phase="monolayer", ownership="focal_work",
                                         evidence=[title_ev]))
    methods = {
        "PBE": ("DFT", "PBE"), "HSE03": ("hybrid_DFT", "HSE03"),
        "HSE06": ("hybrid_DFT", "HSE06"), "G0W0": ("GW", None),
        "GW0": ("partially_self_consistent_GW", None), "GW": ("self_consistent_GW", None),
        "HSE06-G0W0": ("hybrid_DFT_then_G0W0", "HSE06"),
    }
    for row in compute_e_rows():
        evidence = _ev(case, 5, row["source_line"], kind=SourceType.table,
                       locator=f"Table 1;SOC={row['soc']}", table_id="Table 1")
        for key, raw in row["raw_cells"].items():
            if raw in {"–", "-", "—"}:
                continue
            method, functional = methods[key]
            draft.calculations.append(DraftCalculation(
                local_id=f"alsb_{row['soc']}_{key.lower().replace('-', '_')}",
                calculation_type="electronic_band_structure",
                material_refs=["alsb_monolayer"], code="VASP", method=method,
                functional=functional,
                model={"spin_orbit_coupling": row["soc"] == "with", "reported_level": key,
                       "pseudopotential_method": "PAW", "k_mesh": "12x12x1 Gamma-centered",
                       "plane_wave_cutoff_ev": 450, "force_criterion_ev_per_angstrom": 1e-3,
                       "energy_difference_criterion_ev": 1e-7,
                       "van_der_waals": "DFT-D2", "vacuum_angstrom": 20,
                       "note": "Common DFT setup; GW convergence settings are separately described in source."},
                outputs=[_measurement("calculated_band_gap", raw, "eV", evidence,
                                      "AlSb monolayer", calculated=True, method=method,
                                      conditions={"spin_orbit_coupling": row["soc"] == "with", "reported_level": key})],
                ownership="focal_work", evidence=[evidence],
            ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_table_v1")


def recover_review_f():
    case = "SEM-REVIEW-F"
    first_page = page_text(case, 1)
    if "REVIEW ARTICLE" not in first_page.upper() or "the review presented here" not in first_page.casefold():
        raise ValueError("SEM-REVIEW-F lacks independent publisher and author review signals")
    first = _ev(case, 1, _line(case, 1, "60 mV per"))
    second = _ev(case, 2, _line(case, 2, "100 mV per"))
    draft = ExtractedDocument(source=_source(case))
    draft.experiments.extend([
        DraftExperiment(local_id="review_thermal_limit", experiment_type="literature_review_summary",
                        outputs=[_measurement("subthreshold_swing", "60", "mV/dec", first,
                                              "literature MOSFET")], ownership="review_summary", evidence=[first]),
        DraftExperiment(local_id="review_cited_device", experiment_type="cited_literature_comparison",
                        outputs=[_measurement("subthreshold_swing", "100", "mV/dec", second,
                                              "cited nanoscale MOSFET")], ownership="cited_prior_work", evidence=[second]),
    ])
    return assemble_archive(draft, domain="semiconductors", model="review_containment_v1")


def recover_neg_g() -> dict:
    case = "SEM-NEG-G"
    text = page_text(case, 1)
    if not all(term in text for term in ("Perovskite", "Solar Cells", "FTO", "TiO2")):
        raise ValueError("SEM-NEG-G photovoltaic truth anchors missing")
    # The page-1 abstract alone is not enough for this router; Table 2/page 8
    # supplies decisive PV device metrics, exactly as in the locked PV corpus.
    routed = DomainRouter().route_text(text + "\n" + page_text(case, 8))
    return {"case_id": case, "routed_domain": routed.domain,
            "semiconductor_archives": 0, "semiconductor_outputs": 0,
            "source_title": source_lock(case)["source_title"]}


def mixed_h_rows() -> tuple[list[dict], list[dict]]:
    case = "SEM-MIXED-H"
    page4, page5 = page_text(case, 4), page_text(case, 5)
    mobility_lines = [line for line in page4.splitlines() if "linear/" in line and "saturation" in line]
    if len(mobility_lines) != 2:
        raise ValueError("SEM-MIXED-H mobility lines not uniquely identified")
    experimental = []
    for carrier, exponent, line in (("electron", -2, mobility_lines[0]), ("hole", -3, mobility_lines[1])):
        # Publisher PDF text encodes multiplication/minus as /C2 and /C0.
        match = re.search(r"(\d+\.\d+)\s*/C2\s*10\s*/C0\s*([23])", line)
        if not match or int(match[2]) != -exponent:
            raise ValueError(f"SEM-MIXED-H mobility scale ambiguous: {line}")
        experimental.append({"property": f"{carrier}_mobility", "raw_value": match[1],
                             "unit": f"×10^{exponent} cm^2/V/s", "value": float(match[1]),
                             "normalized": float(match[1]) * 10 ** exponent,
                             "page": 4, "source_line": line})
    match = re.search(r"(\d+) nm \(Peak 1\), (\d+) nm \(Peak 2\) and (\d+) nm \(Peak 3\)", page5)
    if not match:
        raise ValueError("SEM-MIXED-H EL peaks missing")
    peak_line = _line(case, 5, "750 nm (Peak 1)")
    for peak, raw in enumerate(match.groups(), start=1):
        experimental.append({"property": "emission_wavelength", "raw_value": raw,
                             "unit": "nm", "value": float(raw), "peak": peak,
                             "page": 5, "source_line": peak_line})
    flat = " ".join(page4.split())
    electron = re.search(r"tetragonal:\s*(\d+\.\d+)\s*m0,\s*orthorhombic:\s*(\d+\.\d+)\s*m0", flat)
    hole = re.search(r"holes \(tetragonal:\s*(\d+\.\d+)\s*m0,\s*orthorhombic:\s*(\d+\.\d+)\s*m0", flat)
    if not electron or not hole:
        raise ValueError("SEM-MIXED-H DFT masses missing")
    computational = []
    for carrier, found in (("electron", electron), ("hole", hole)):
        for phase, raw in zip(("tetragonal", "orthorhombic"), found.groups()):
            source_line = _line(case, 4, raw)
            computational.append({"property": "calculated_effective_mass", "raw_value": raw,
                                  "unit": "m0", "value": float(raw), "carrier": carrier,
                                  "phase": phase, "page": 4, "source_line": source_line})
    return experimental, computational


def recover_mixed_h():
    case = "SEM-MIXED-H"
    draft = ExtractedDocument(source=_source(case))
    substrate_ev = _ev(case, 2, _line(case, 2, "SiO 2/Si"))
    film_ev = _ev(case, 2, _line(case, 2, "of the CH 3NH3PbI3 thin"))
    device_ev = _ev(case, 2, _line(case, 2, "bottom-gate, bottom contact"))
    anneal_ev = _ev(case, 7, _line(case, 7, "annealed at 100"))
    draft.materials.extend([
        DraftMaterial(local_id="si_sio2", name="p++ Si with thermally grown SiO2",
                      tags=["substrate", "gate_dielectric"], ownership="focal_work", evidence=[substrate_ev]),
        DraftMaterial(local_id="mapbi3", name="methylammonium lead iodide thin film",
                      formula="CH3NH3PbI3", tags=["semiconductor_film"], ownership="focal_work",
                      evidence=[film_ev]),
    ])
    draft.devices.append(DraftDevice(
        local_id="le_fet", name="CH3NH3PbI3 LE-FET", device_type="semiconductor_device",
        layer_stack=[DraftDeviceLayer(sequence_index=0, role="substrate", material_ref="si_sio2",
                                      evidence=[substrate_ev]),
                     DraftDeviceLayer(sequence_index=1, role="semiconductor_film", material_ref="mapbi3",
                                      evidence=[film_ev])],
        configuration={"sample_label": "CH3NH3PbI3 LE-FET", "device_geometry": "bottom-gate bottom-contact",
                       "electrodes": "Ni (10 nm) and Au (50 nm)", "film_preparation": "spin coating"},
        ownership="focal_work", evidence=[device_ev, film_ev],
    ))
    draft.processes.append(DraftProcess(
        local_id="spin_coat_anneal", name="two-step spin coating and annealing",
        family="solution_processing", output_material_refs=["mapbi3"], output_device_refs=["le_fet"],
        parameters=[Measurement(property="annealing_temperature", raw_value="100", value=100,
                                unit="C", qualifier="exact", conditions={"scientific_type": "reported_process_parameter",
                                                                      "sample_label": "CH3NH3PbI3 LE-FET"}, evidence=[anneal_ev]),
                    Measurement(property="annealing_time", raw_value="30", value=30,
                                unit="min", qualifier="exact", conditions={"scientific_type": "reported_process_parameter",
                                                                        "sample_label": "CH3NH3PbI3 LE-FET"}, evidence=[anneal_ev])],
        ownership="focal_work", evidence=[anneal_ev],
    ))
    experimental, computational = mixed_h_rows()
    transport = []
    optical = []
    for row in experimental:
        evidence = _ev(case, row["page"], row["source_line"])
        kwargs = {"conditions": {"measurement_temperature": "78 K", "device_id": "le_fet"}}
        if "normalized" in row:
            kwargs["normalized"] = (row["normalized"], "cm^2/V/s")
            kwargs["conditions"]["carrier_identity"] = row["property"].split("_", 1)[0]
        if "peak" in row:
            kwargs["conditions"]["emission_peak_index"] = row["peak"]
        item = _measurement(row["property"], row["raw_value"], row["unit"], evidence,
                            "CH3NH3PbI3 LE-FET", **kwargs)
        (optical if "peak" in row else transport).append(item)
    for local_id, kind, outputs in (("transport_78k", "field_effect_transport", transport),
                                    ("emission_78k", "electroluminescence", optical)):
        draft.experiments.append(DraftExperiment(local_id=local_id, experiment_type=kind,
                                                material_refs=["mapbi3"], device_refs=["le_fet"],
                                                outputs=outputs, ownership="focal_work",
                                                evidence=[output.evidence[0] for output in outputs]))
    calc_ev = _ev(case, 7, _line(case, 7, "DFT calculations"))
    draft.calculations.append(DraftCalculation(
        local_id="dft_effective_masses", calculation_type="band_structure_effective_mass",
        material_refs=["mapbi3"], code="Quantum ESPRESSO", method="DFT", functional="PBE",
        model={"spin_orbit_coupling": "included and excluded band-structure comparisons",
               "plane_wave_cutoff_ry": 40, "k_mesh": "4x4x4", "pseudopotential": "ultrasoft",
               "phases": ["tetragonal", "orthorhombic"]},
        outputs=[_measurement(row["property"], row["raw_value"], row["unit"],
                              _ev(case, row["page"], row["source_line"]),
                              "CH3NH3PbI3", calculated=True,
                              conditions={"carrier_identity": row["carrier"], "phase": row["phase"]})
                 for row in computational],
        ownership="focal_work", evidence=[calc_ev],
    ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_text_v1")
