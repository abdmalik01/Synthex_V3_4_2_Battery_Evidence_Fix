"""Deterministic, source-table-driven interim recovery for four semiconductor cases."""

from __future__ import annotations

import re

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftDevice, DraftDeviceLayer, DraftExperiment, DraftMaterial, DraftProcess,
    DraftSource, ExtractedDocument,
)

from .source_tables import (
    gold_a_rows, optical_c_rows, page_text, process_d_rows, transport_b_rows,
)


_SOURCES = {
    "SEM-GOLD-A": DraftSource(
        title="Highly conductive and transparent gallium doped zinc oxide thin films via chemical vapor deposition",
        doi="10.1038/s41598-020-57532-7", year=2020,
        url="https://www.nature.com/articles/s41598-020-57532-7",
        authors=["Sapna D. Ponja", "Sanjayan Sathasivam", "Ivan P. Parkin", "Claire J. Carmalt"],
    ),
    "SEM-TRANSPORT-B": DraftSource(
        title="Effects of doping and annealing on properties of ZnO films grown by atomic layer deposition",
        doi="10.1186/s11671-015-0801-y", year=2015,
        url="https://link.springer.com/article/10.1186/s11671-015-0801-y",
        authors=["Aiji Wang", "Tingfang Chen", "Shuhua Lu", "Zhenglong Wu", "Yongliang Li", "He Chen", "Yinshu Wang"],
    ),
    "SEM-OPTICAL-C": DraftSource(
        title="Comparison of the Material Quality of AlxIn1−xN (x—0–0.50) Films Deposited on Si(100) and Si(111) at Low Temperature by Reactive RF Sputtering",
        doi="10.3390/ma15207373", year=2022,
        url="https://www.mdpi.com/1996-1944/15/20/7373",
        authors=["Michael Sun", "Rodrigo Blasco", "Julian Nwodo", "María de la Mata", "Sergio I. Molina", "Akhil Ajay", "Eva Monroy", "Sirona Valdueza-Felip", "Fernando B. Naranjo"],
    ),
    "SEM-PROCESS-D": DraftSource(
        title="Reference of Temperature and Time during tempering process for non-stoichiometric FTO films",
        doi="10.1038/srep15001", year=2015,
        url="https://www.nature.com/articles/srep15001",
        authors=["J. K. Yang", "B. Liang", "M. J. Zhao", "Y. Gao", "F. C. Zhang", "H. L. Zhao"],
    ),
}


def _table_evidence(case: str, page: int, table: str, line: str, row: str) -> Evidence:
    return Evidence(page=page, source_type=SourceType.table,
                    original_source_type="publisher_pdf_table", verbatim_match=True,
                    text_snippet=line, table_id=table, locator=f"{table};row={row}")


def _text_evidence(case: str, page: int, needle: str, *, following: int = 0) -> Evidence:
    text = page_text(case, page)
    lines = text.splitlines()
    index = next((index for index, line in enumerate(lines) if needle in line), None)
    if index is None:
        raise ValueError(f"Source text not found: {case} page {page} {needle!r}")
    line = "\n".join(part.strip() for part in lines[index:index + following + 1])
    return Evidence(page=page, source_type=SourceType.text,
                    original_source_type="publisher_pdf_text", verbatim_match=True,
                    text_snippet=line, locator=f"page={page};text={needle}")


def _measurement(property_name: str, raw: str, value: float, unit: str,
                 evidence: Evidence, sample: str, *, scientific_type: str = "reported_measurement",
                 method: str | None = None, conditions: dict | None = None,
                 normalized: tuple[float, str] | None = None) -> Measurement:
    return Measurement(property=property_name, raw_value=raw, value=value, unit=unit,
                       normalized_value=normalized[0] if normalized else None,
                       normalized_unit=normalized[1] if normalized else None,
                       qualifier="exact", method=method,
                       conditions={"sample_label": sample, "scientific_type": scientific_type,
                                   **(conditions or {})}, evidence=[evidence])


def _film(draft: ExtractedDocument, *, local_id: str, label: str, formula: str,
          substrate_ref: str, substrate_evidence: Evidence, film_evidence: Evidence,
          thickness: Measurement | None = None, composition: dict[str, float] | None = None,
          dopants: list[dict] | None = None) -> str:
    draft.materials.append(DraftMaterial(
        local_id=local_id, name=label, formula=formula, composition=composition or {},
        dopants=dopants or [], tags=["semiconductor_film"],
        ownership="focal_work", evidence=[film_evidence],
    ))
    device_id = f"specimen_{local_id}"
    draft.devices.append(DraftDevice(
        local_id=device_id, name=label, device_type="semiconductor_thin_film",
        layer_stack=[
            DraftDeviceLayer(sequence_index=0, role="substrate", material_ref=substrate_ref,
                             evidence=[substrate_evidence]),
            DraftDeviceLayer(sequence_index=1, role="semiconductor_film", material_ref=local_id,
                             thickness=thickness, evidence=[film_evidence]),
        ],
        configuration={"sample_label": label, "specimen_kind": "thin_film"},
        ownership="focal_work", evidence=[film_evidence],
    ))
    return device_id


def recover_gold_a():
    case = "SEM-GOLD-A"
    draft = ExtractedDocument(source=_SOURCES[case].model_copy(deep=True))
    substrate_ev = _text_evidence(case, 5, "SiO2 barrier coated float glass")
    growth_ev = _text_evidence(case, 2, "450")
    draft.materials.append(DraftMaterial(local_id="float_glass", name="SiO2-barrier-coated float glass",
                                          tags=["substrate"], ownership="focal_work", evidence=[substrate_ev]))
    for index, row in enumerate(gold_a_rows()):
        label = f"A-{row['film']}"
        table_ev = _table_evidence(case, 4, "Table 2", row["source_line"], row["film"])
        thickness = _measurement("film_thickness", row["raw_cells"]["thickness_nm"], row["thickness_nm"],
                                 "nm", table_ev, label, scientific_type="reported_process_parameter")
        film_id = f"film_{index}"
        device_id = _film(draft, local_id=film_id, label=label, formula=row["film"],
                          substrate_ref="float_glass", substrate_evidence=substrate_ev,
                          film_evidence=table_ev, thickness=thickness,
                          dopants=[{"element": "Ga", "nominal_atomic_percent": row["ga_atomic_percent"]}] if row["ga_atomic_percent"] else [])
        draft.processes.append(DraftProcess(
            local_id=f"aacvd_{index}", name="AACVD ZnO:Ga film growth", family="aerosol_assisted_cvd",
            output_material_refs=[film_id], output_device_refs=[device_id],
            parameters=[_measurement("growth_temperature", "450", 450, "C", growth_ev, label,
                                     scientific_type="reported_process_parameter"), thickness],
            ownership="focal_work", evidence=[growth_ev, table_ev],
        ))
        columns = (
            ("carrier_concentration", "carrier_concentration_scaled", "×10^20 cm^-3", "Hall_effect", (row["carrier_concentration_scaled"] * 1e20, "cm^-3")),
            ("hall_mobility", "hall_mobility", "cm^2/V/s", "Hall_effect", None),
            ("resistivity", "resistivity_scaled", "×10^-3 Ω·cm", "Hall_effect", (row["resistivity_scaled"] * 1e-3, "Ω·cm")),
            ("sheet_resistance", "sheet_resistance", "Ω/sq", "Hall_effect", None),
            ("optical_band_gap", "optical_band_gap", "eV", "UV_vis_Tauc", None),
        )
        outputs = []
        for prop, key, unit, method, normalized in columns:
            conditions = {"substrate": "SiO2-barrier-coated float glass", "carrier_type": "n-type",
                          "measurement_method": method}
            if prop == "optical_band_gap":
                conditions["derivation_basis"] = "UV-vis Tauc fit"
            outputs.append(_measurement(prop, row["raw_cells"][key], row[key], unit, table_ev,
                                        label, method=method, conditions=conditions, normalized=normalized))
        draft.experiments.append(DraftExperiment(
            local_id=f"measurement_{index}", experiment_type="Hall_and_UV_vis",
            material_refs=[film_id], device_refs=[device_id], outputs=outputs,
            ownership="focal_work", evidence=[table_ev],
        ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_table_v1")


def recover_transport_b():
    case = "SEM-TRANSPORT-B"
    draft = ExtractedDocument(source=_SOURCES[case].model_copy(deep=True))
    substrate_ev = _text_evidence(case, 2, "glass")
    growth_ev = _text_evidence(case, 2, "150")
    anneal_ev = _text_evidence(case, 2, "350")
    time_ev = _text_evidence(case, 3, "20 min")
    draft.materials.append(DraftMaterial(local_id="glass", name="glass substrate", tags=["substrate"],
                                          ownership="focal_work", evidence=[substrate_ev]))
    for index, row in enumerate(transport_b_rows()):
        label = f"B-Al{row['al_atomic_percent']}-{row['state']}"
        table_ev = _table_evidence(case, 8, "Table 2", row["source_line"], label)
        film_id = f"film_{index}"
        device_id = _film(draft, local_id=film_id, label=label, formula="ZnO",
                          substrate_ref="glass", substrate_evidence=substrate_ev, film_evidence=table_ev,
                          dopants=[{"element": "Al", "ideal_atomic_percent": row["al_atomic_percent"]}] if row["al_atomic_percent"] else [])
        params = [_measurement("growth_temperature", "150", 150, "C", growth_ev, label,
                               scientific_type="reported_process_parameter")]
        if row["state"] != "as_grown":
            params.extend([
                _measurement("annealing_temperature", "350", 350, "C", anneal_ev, label,
                             scientific_type="reported_process_parameter"),
                _measurement("annealing_time", "20", 20, "min", time_ev, label,
                             scientific_type="reported_process_parameter"),
            ])
        draft.processes.append(DraftProcess(
            local_id=f"process_{index}", name=f"ALD {row['state']}",
            family="atomic_layer_deposition_then_anneal" if row["state"] != "as_grown" else "atomic_layer_deposition",
            atmosphere={"annealed_air": "air", "annealed_ar": "Ar", "annealed_n2": "N2"}.get(row["state"]),
            output_material_refs=[film_id], output_device_refs=[device_id], parameters=params,
            ownership="focal_work", evidence=[table_ev, growth_ev],
        ))
        outputs = []
        for prop, unit in (("resistivity", "Ω·cm"), ("carrier_concentration", "cm^-3"),
                           ("carrier_mobility", "cm^2/V/s")):
            value = row[prop]
            if value is None:
                continue
            outputs.append(_measurement(prop, row["raw_cells"][prop], value, unit, table_ev,
                                        label, method="van_der_pauw",
                                        conditions={"measurement_temperature": "room_temperature",
                                                    "processing_state": row["state"],
                                                    "nominal_al_atomic_percent": row["al_atomic_percent"]}))
        draft.experiments.append(DraftExperiment(
            local_id=f"measurement_{index}", experiment_type="van_der_pauw_transport",
            material_refs=[film_id], device_refs=[device_id], outputs=outputs,
            ownership="focal_work", evidence=[table_ev],
        ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_table_v1")


def recover_optical_c():
    case = "SEM-OPTICAL-C"
    draft = ExtractedDocument(source=_SOURCES[case].model_copy(deep=True))
    absorb_rows, pl_rows, film_context = optical_c_rows()
    sapphire_ev = _text_evidence(case, 6, "sapphire")
    si100_ev = _text_evidence(case, 3, "Si(100)")
    si111_ev = _text_evidence(case, 3, "Si(111)")
    growth_ev = _text_evidence(case, 1, "300")
    for substrate_id, name, evidence in (("sapphire", "sapphire substrate", sapphire_ev),
                                         ("si100", "Si(100) substrate", si100_ev),
                                         ("si111", "Si(111) substrate", si111_ev)):
        draft.materials.append(DraftMaterial(local_id=substrate_id, name=name, tags=["substrate"],
                                              ownership="focal_work", evidence=[evidence]))
    for index, row in enumerate(absorb_rows):
        label = f"C-{row['sample']}-sapphire"
        ev = _table_evidence(case, 6, "Table 2", row["source_line"], label)
        film_id = f"abs_film_{index}"
        device_id = _film(draft, local_id=film_id, label=label,
                          formula="InN" if row["al_mole_fraction"] == 0 else "AlxIn1-xN",
                          substrate_ref="sapphire", substrate_evidence=sapphire_ev, film_evidence=ev,
                          composition={"Al": row["al_mole_fraction"], "In": 1-row["al_mole_fraction"]})
        draft.processes.append(DraftProcess(
            local_id=f"growth_abs_{index}", name="reactive RF sputtering", family="reactive_rf_sputtering",
            output_material_refs=[film_id], output_device_refs=[device_id],
            parameters=[_measurement("growth_temperature", "300", 300, "C", growth_ev,
                                     label, scientific_type="reported_process_parameter")],
            ownership="focal_work", evidence=[growth_ev, ev],
        ))
        output = _measurement("optical_band_gap", row["raw_cell"], row["apparent_optical_band_gap_ev"],
                              "eV", ev, label, scientific_type="reported_derived_metric",
                              method="absorption_fit",
                              conditions={"substrate": "sapphire", "measurement_temperature": "room_temperature",
                                          "derivation_basis": "linear fit to squared absorption coefficient",
                                          "apparent": True})
        draft.experiments.append(DraftExperiment(
            local_id=f"absorption_{index}", experiment_type="UV_vis_absorption",
            material_refs=[film_id], device_refs=[device_id], outputs=[output],
            ownership="focal_work", evidence=[ev],
        ))
    # The same Si specimen is measured at both PL temperatures; do not make two films.
    si_devices: dict[tuple[str, str], tuple[str, str]] = {}
    for index, ((sample, substrate), film) in enumerate(sorted(film_context.items())):
        if sample not in {"M1", "M2"}:
            continue
        label = f"C-{sample}-{substrate}"
        context_ev = _table_evidence(case, 3, "Table 1", film["source_line"], label)
        thickness = _measurement("film_thickness", str(film["thickness_nm"]), film["thickness_nm"],
                                 "nm", context_ev, label, scientific_type="reported_process_parameter")
        film_id = f"pl_film_{index}"
        device_id = _film(draft, local_id=film_id, label=label,
                          formula="InN" if film["al_mole_fraction"] == 0 else "AlxIn1-xN",
                          substrate_ref="si100" if substrate == "Si(100)" else "si111",
                          substrate_evidence=si100_ev if substrate == "Si(100)" else si111_ev,
                          film_evidence=context_ev, thickness=thickness,
                          composition={"Al": film["al_mole_fraction"], "In": 1-film["al_mole_fraction"]})
        si_devices[(sample, substrate)] = (film_id, device_id)
        draft.processes.append(DraftProcess(
            local_id=f"growth_pl_{index}", name="reactive RF sputtering", family="reactive_rf_sputtering",
            output_material_refs=[film_id], output_device_refs=[device_id],
            parameters=[_measurement("growth_temperature", "300", 300, "C", growth_ev,
                                     label, scientific_type="reported_process_parameter"), thickness],
            ownership="focal_work", evidence=[growth_ev, context_ev],
        ))
    for index, row in enumerate(pl_rows):
        film_id, device_id = si_devices[(row["sample"], row["substrate"])]
        label = f"C-{row['sample']}-{row['substrate']}"
        ev = _table_evidence(case, 8, "Table 3", row["source_line"],
                             f"{label}-{row['measurement_temperature_k']}K")
        output = _measurement("photoluminescence_peak", row["raw_cell"], row["pl_peak_ev"],
                              "eV", ev, label, method="photoluminescence",
                              conditions={"substrate": row["substrate"],
                                          "measurement_temperature": row["measurement_temperature_k"],
                                          "measurement_temperature_unit": "K"})
        draft.experiments.append(DraftExperiment(
            local_id=f"pl_{index}", experiment_type="photoluminescence",
            material_refs=[film_id], device_refs=[device_id], outputs=[output],
            ownership="focal_work", evidence=[ev],
        ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_table_v1")


def recover_process_d():
    case = "SEM-PROCESS-D"
    draft = ExtractedDocument(source=_SOURCES[case].model_copy(deep=True))
    substrate_ev = _text_evidence(case, 5, "glass substrate coated", following=1)
    growth_ev = _text_evidence(case, 2, "650")
    time_group_ev = _table_evidence(case, 2, "Table 1", "680 °C 220 s", "merged_time_220_s")
    temp_group_ev = _table_evidence(case, 2, "Table 1", "700 °C 220 s", "merged_temperature_700_c")
    draft.materials.append(DraftMaterial(local_id="glass", name="SiOxCy-coated glass substrate",
                                          tags=["substrate"], ownership="focal_work", evidence=[substrate_ev]))
    for index, row in enumerate(process_d_rows()):
        label = f"D-{row['series']}-{row['tempering_temperature_c']}C-{row['tempering_time_s']}s"
        ev = _table_evidence(case, 2, "Table 1", row["source_line"], label)
        film_id = f"film_{index}"
        device_id = _film(draft, local_id=film_id, label=label, formula="SnO2",
                          substrate_ref="glass", substrate_evidence=substrate_ev,
                          film_evidence=ev, dopants=[{"element": "F", "concentration": "not_sample_specific"}])
        temp_ev = ev if row["temperature_cell"] else temp_group_ev
        time_ev = ev if row["time_cell"] else time_group_ev
        params = [
            _measurement("growth_temperature", "650", 650, "C", growth_ev, label,
                         scientific_type="reported_process_parameter"),
            _measurement("tempering_temperature", str(row["tempering_temperature_c"]),
                         row["tempering_temperature_c"], "C", temp_ev, label,
                         scientific_type="reported_process_parameter"),
            _measurement("tempering_time", str(row["tempering_time_s"]),
                         row["tempering_time_s"], "s", time_ev, label,
                         scientific_type="reported_process_parameter"),
        ]
        draft.processes.append(DraftProcess(
            local_id=f"process_{index}", name="APCVD and FTO tempering", family="apcvd_then_tempering",
            output_material_refs=[film_id], output_device_refs=[device_id], parameters=params,
            ownership="focal_work", evidence=[ev, growth_ev],
        ))
        outputs = [
            _measurement("hall_coefficient", row["raw_cells"]["hall_coefficient_scaled"],
                         row["hall_coefficient_scaled"], "×10^-2 cm^3/C", ev, label,
                         method="Hall_effect", normalized=(row["hall_coefficient_scaled"] * 1e-2, "cm^3/C"),
                         conditions={"measurement_temperature": 300, "measurement_temperature_unit": "K",
                                     "processing_series": row["series"]}),
            _measurement("crystallite_size", row["raw_cells"]["crystallite_size_nm"],
                         row["crystallite_size_nm"], "nm", ev, label, method="XRD_Debye_Scherrer",
                         conditions={"processing_series": row["series"]}),
        ]
        draft.experiments.append(DraftExperiment(
            local_id=f"measurement_{index}", experiment_type="Hall_and_XRD",
            material_refs=[film_id], device_refs=[device_id], outputs=outputs,
            ownership="focal_work", evidence=[ev],
        ))
    return assemble_archive(draft, domain="semiconductors", model="deterministic_pdf_table_v1")


RECOVER = {
    "SEM-GOLD-A": recover_gold_a,
    "SEM-TRANSPORT-B": recover_transport_b,
    "SEM-OPTICAL-C": recover_optical_c,
    "SEM-PROCESS-D": recover_process_d,
}


def recover_all_cases():
    return {case: recover() for case, recover in RECOVER.items()}
