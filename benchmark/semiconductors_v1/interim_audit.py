"""Source-locked four-case semiconductor audit; deliberately not a V1 freeze."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

from synthex_platform.core.models import Evidence, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.semiconductors_contract import (
    _RESULT_FAMILIES, semiconductor_admission_decision,
)

from .recover_cases import recover_all_cases
from .source_tables import (
    ROOT, gold_a_rows, optical_c_rows, page_text, process_d_rows, source_lock,
    transport_b_rows,
)


def _gold(case: str) -> dict:
    lock = source_lock(case)
    return json.loads((ROOT / lock["gold_file"]).read_text(encoding="utf-8"))


def _rows_equal(gold: list[dict], parsed: list[dict]) -> bool:
    return len(gold) == len(parsed) and all(
        all(
            math.isclose(row.get(key), value, rel_tol=1e-12, abs_tol=1e-15)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and isinstance(row.get(key), (int, float))
            else row.get(key) == value
            for key, value in expected.items()
        )
        for expected, row in zip(gold, parsed)
    )


def run_interim_audit() -> dict:
    golds = {case: _gold(case) for case in (
        "SEM-GOLD-A", "SEM-TRANSPORT-B", "SEM-OPTICAL-C", "SEM-PROCESS-D"
    )}
    a_rows = gold_a_rows()
    b_rows = transport_b_rows()
    c_abs, c_pl, _ = optical_c_rows()
    d_rows = process_d_rows()
    source_parity = {
        "SEM-GOLD-A": _rows_equal(golds["SEM-GOLD-A"]["rows"], a_rows),
        "SEM-TRANSPORT-B": _rows_equal(golds["SEM-TRANSPORT-B"]["rows"], b_rows),
        "SEM-OPTICAL-C": _rows_equal(golds["SEM-OPTICAL-C"]["absorption_specimens"], c_abs)
            and _rows_equal(golds["SEM-OPTICAL-C"]["pl_specimens"], c_pl),
        "SEM-PROCESS-D": _rows_equal(golds["SEM-PROCESS-D"]["rows"], d_rows),
    }
    archives = recover_all_cases()
    results = {
        case: [output for exp in archive.experiments for output in exp.outputs]
        for case, archive in archives.items()
    }
    projected = {
        case: [row for row in project_results_rows(archive)
               if row["measurement_role"] == "result" and row["admission_status"] == "canonical"]
        for case, archive in archives.items()
    }
    all_outputs = [output for outputs in results.values() for output in outputs]
    all_rows = [row for rows in projected.values() for row in rows]
    all_experiments = [item for archive in archives.values() for item in archive.experiments]
    all_devices = [item for archive in archives.values() for item in archive.devices]
    quarantine = {case: archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
                  for case, archive in archives.items()}
    a = archives["SEM-GOLD-A"]
    b = archives["SEM-TRANSPORT-B"]
    c = archives["SEM-OPTICAL-C"]
    d = archives["SEM-PROCESS-D"]
    a_output = results["SEM-GOLD-A"][0]
    caption_output = a_output.model_copy(deep=True)
    caption_output.evidence = [Evidence(
        page=4, source_type=SourceType.figure_caption,
        original_source_type="figure_caption", verbatim_match=True,
        text_snippet=a_output.raw_value, locator="figure=4;caption",
    )]
    missing_output = a_output.model_copy(deep=True)
    missing_output.raw_value = "N/A"
    router = DomainRouter()
    positives = {
        case: router.route_text(page_text(case, 1) + page_text(case, source_lock(case)["decisive_pages"][-1])).domain
        for case in archives
    }
    negative_routes = {
        "photovoltaics": router.route_text("Perovskite semiconductor solar cell with band gap and carrier mobility. We measured PCE, Voc, Jsc and fill factor under AM1.5G.").domain,
        "thermoelectrics": router.route_text("Thermoelectric semiconductor transport: we measured Seebeck coefficient, power factor, zT and mobility as a function of temperature.").domain,
        "batteries": router.route_text("Lithium-ion battery separator coating. We measured charge-discharge capacity and coulombic efficiency.").domain,
        "catalysis": router.route_text("Photocatalyst semiconductor film for hydrogen evolution. We measured HER overpotential and reaction rate.").domain,
    }

    def inv(number: int, name: str, passed: bool, evidence: str) -> dict:
        return {"number": number, "name": name, "passed": bool(passed), "evidence": evidence}

    props = set(_RESULT_FAMILIES)
    a_properties = {o.property for o in results["SEM-GOLD-A"]}
    c_properties = {o.property for o in results["SEM-OPTICAL-C"]}
    invariants = [
        inv(1, "electronic band gap != optical band gap", {"electronic_band_gap", "optical_band_gap"} <= props, "Separate canonical keys and derivation requirements."),
        inv(2, "band gap != PL peak", {"optical_band_gap", "photoluminescence_peak"} == c_properties, "C Table 2 absorption and Table 3 PL remain separate outputs."),
        inv(3, "work function != electron affinity", {"work_function", "electron_affinity"} <= props, "Distinct result keys."),
        inv(4, "work function != ionization energy", {"work_function", "ionization_energy"} <= props, "Distinct result keys."),
        inv(5, "carrier concentration != dopant concentration", "carrier_concentration" in a_properties and all(o.property != "dopant_concentration" for o in all_outputs), "Ga/Al atomic fractions are specimen composition; no cm^-3 dopant density is fabricated."),
        inv(6, "electron concentration != hole concentration", {"electron_concentration", "hole_concentration"} <= props, "Separate property keys."),
        inv(7, "mobility != conductivity", {"carrier_mobility", "conductivity"} <= props and "conductivity" not in a_properties, "No inversion or relabeling."),
        inv(8, "Hall mobility retains method identity", all(o.method == "Hall_effect" for o in results["SEM-GOLD-A"] if o.property == "hall_mobility"), "A Hall mobility explicitly carries Hall method."),
        inv(9, "conductivity != resistivity", {"conductivity", "resistivity"} <= props and "resistivity" in a_properties, "Separate families and units."),
        inv(10, "sheet resistance != bulk resistivity", {"sheet_resistance", "resistivity"} <= a_properties, "A Table 2 retains Ω/sq and scaled Ω·cm separately."),
        inv(11, "contact resistance != sheet resistance", {"contact_resistance", "sheet_resistance"} <= props, "Distinct result keys and unit families."),
        inv(12, "threshold voltage != operating voltage", "threshold_voltage" in props and "operating_voltage" not in props, "Operating bias is not admitted as a threshold result."),
        inv(13, "breakdown voltage != breakdown field", {"breakdown_voltage", "breakdown_field"} <= props, "Distinct V and V/cm families."),
        inv(14, "current != current density", "current_density" in props and "current" not in props, "Current is not silently mapped to A/cm²."),
        inv(15, "film thickness != depletion width", all(layer["thickness"]["property"] == "film_thickness" for device in all_devices for layer in device.configuration["layer_stack"] if "thickness" in layer) and "depletion_width" not in props, "Only source-backed film thickness is carried."),
        inv(16, "substrate != semiconductor film", all([layer["role"] for layer in device.configuration["layer_stack"]] == ["substrate", "semiconductor_film"] and device.material_ids[0] != device.material_ids[1] for device in all_devices), "Every specimen has separate substrate and film layers."),
        inv(17, "growth temperature != measurement temperature", all("measurement_temperature" not in o.conditions for o in results["SEM-GOLD-A"]) and all(any(p.property == "growth_temperature" for p in process.parameters) for process in a.processes), "A 450°C growth is process-only; Hall temperature remains unreported."),
        inv(18, "annealing temperature != measurement temperature", all(o.conditions.get("measurement_temperature") == "room_temperature" for o in results["SEM-TRANSPORT-B"]) and all(any(p.property == "annealing_temperature" for p in process.parameters) for process in b.processes if "annealed" in process.name), "B 350°C anneal and room-temperature measurements are separate."),
        inv(19, "measured != computational", all(not archive.calculations for archive in archives.values()) and all(row["record_type"] == "experiment" for row in all_rows), "First four cases are experimental only; calculation record remains separate."),
        inv(20, "calculated band gap != measured band gap", {"calculated_band_gap", "optical_band_gap"} <= props and all(o.property != "calculated_band_gap" for o in all_outputs), "Calculated key is not populated by Tauc gaps."),
        inv(21, "calculated effective mass != measured mobility", {"calculated_effective_mass", "carrier_mobility"} <= props and not any(o.property == "calculated_effective_mass" for o in all_outputs), "Separate units and modality."),
        inv(22, "dopant identity retained", any(m.dopants and m.dopants[0]["element"] == "Ga" for m in a.materials) and any(m.dopants and m.dopants[0]["element"] == "Al" for m in b.materials) and any(m.dopants and m.dopants[0]["element"] == "F" for m in d.materials), "Ga, Al and F identities remain source-specific."),
        inv(23, "dopant concentration not conflated with nominal fraction", all("nominal_atomic_percent" in m.dopants[0] for m in a.materials if m.dopants) and all("ideal_atomic_percent" in m.dopants[0] for m in b.materials if m.dopants) and all(o.property != "dopant_concentration" for o in all_outputs), "At.% is not converted into cm^-3 dopant concentration."),
        inv(24, "sample/device identity retained", all(len(e.material_ids) == len(e.device_ids) == 1 for e in all_experiments) and len({d.name for d in all_devices}) == len(all_devices), "Every result has a unique film specimen association within its case."),
        inv(25, "missing conditions not inferred", all("measurement_temperature" not in o.conditions for o in results["SEM-GOLD-A"]) and all(o.conditions.get("substrate") == "sapphire" for o in results["SEM-OPTICAL-C"] if o.property == "optical_band_gap"), "A temperature remains missing; C substrate is source-specific."),
        inv(26, "missing values not interpolated", len(results["SEM-TRANSPORT-B"]) == 46 and sum(row[k] is None for row in b_rows for k in ("carrier_concentration", "carrier_mobility")) == 14, "B has 14 dash cells excluded, never zero-filled."),
        inv(27, "caption-only evidence cannot admit", not semiconductor_admission_decision(caption_output, role="result").admitted, "Caption-only value rejected."),
        inv(28, "N/A cannot become numeric", not semiconductor_admission_decision(missing_output, role="result").admitted, "N/A token rejected even with numeric value field."),
        inv(29, "analytics retain material/sample/process/property identity", len(all_rows) == len(all_outputs) == 99 and all(json.loads(row["conditions_json"]).get("sample_label") and json.loads(row["conditions_json"]).get("synthesis_growth_temperature", {}).get("process_id") and row["material_ids"] and row["metric"] for row in all_rows), "One canonical analytics row per result with sample, material, namespaced process and property lineage."),
        inv(30, "archive/domain scoping correct", all(archive.metadata.domain == "semiconductors" for archive in archives.values()) and all(row["domain"] == "semiconductors" for row in all_rows), "All four archives and result rows remain Semiconductor-scoped."),
    ]
    contamination = {
        "ownership": sum(bool(items) for items in quarantine.values()),
        "evidence": sum(not o.evidence or not all(e.verbatim_match is True and e.page and e.table_id and e.locator for e in o.evidence) for o in all_outputs),
        "cross_record_leakage": sum(len(e.device_ids) != 1 or len(e.material_ids) != 1 for e in all_experiments),
        "analytics": abs(len(all_rows) - len(all_outputs)) + sum(row["domain"] != "semiconductors" for row in all_rows),
    }
    case_counts = {
        case: {"materials": len(archive.materials), "devices": len(archive.devices),
               "processes": len(archive.processes), "experiments": len(archive.experiments),
               "calculations": len(archive.calculations), "outputs": len(results[case]),
               "analytics_rows": len(projected[case]), "quarantine": len(quarantine[case])}
        for case, archive in archives.items()
    }
    passed = all(source_parity.values()) and all(item["passed"] for item in invariants) and not any(contamination.values()) and all(value == "semiconductors" for value in positives.values()) and negative_routes == {"photovoltaics": "photovoltaics", "thermoelectrics": "thermoelectrics", "batteries": "batteries", "catalysis": "catalysis"}
    return {"schema": "synthex.semiconductors.interim_audit.v1", "freeze_status": "INTERIM_NOT_FROZEN",
            "source_gold_parity": source_parity, "cases": case_counts,
            "canonical_output_total": len(all_outputs), "invariants": invariants,
            "passed_invariants": sum(item["passed"] for item in invariants),
            "contamination": contamination, "routing": {"positive": positives, "negative": negative_routes},
            "live_gate": {"satisfied": False, "reason": "Offline audit only; current live-provider qualification is recorded separately in live_gate.json."},
            "passed": passed}


if __name__ == "__main__":
    report = run_interim_audit()
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if "--write" in sys.argv:
        (ROOT / "interim_audit.json").write_text(rendered, encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
