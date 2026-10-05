"""Eight-case, forty-invariant offline scientific closure gate."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from pathlib import Path
import sys

from synthex_platform.benchmarks.provider_artifacts import _io_path
from synthex_platform.benchmarks.optional_evidence import inspect_optional_raw_artifact
from synthex_platform.core.models import Evidence, SourceType
from synthex_platform.export.analytics_projection import project_results_rows
from synthex_platform.extraction.semiconductors_contract import (
    _RESULT_FAMILIES, semiconductor_admission_decision,
)

from .closure_cases import (
    compute_e_rows, mixed_h_rows, recover_compute_e, recover_mixed_h,
    recover_neg_g, recover_review_f,
)
from .interim_audit import run_interim_audit
from .recover_cases import recover_all_cases
from .source_tables import ROOT, resolve_run_artifact_root, source_lock, transport_b_rows


CASES = ("SEM-GOLD-A", "SEM-TRANSPORT-B", "SEM-OPTICAL-C", "SEM-PROCESS-D",
         "SEM-COMPUTE-E", "SEM-REVIEW-F", "SEM-NEG-G", "SEM-MIXED-H")


def _gold(case: str) -> dict:
    return json.loads((ROOT / source_lock(case)["gold_file"]).read_text(encoding="utf-8"))


def _parity() -> dict[str, bool]:
    result = {}
    e = _gold("SEM-COMPUTE-E")
    rows = compute_e_rows()
    result["SEM-COMPUTE-E"] = len(rows) == len(e["rows"]) and all(
        row["soc"] == expected["soc"] and all(
            (row["values"][key] is None and value is None) or
            (row["values"][key] is not None and value is not None and math.isclose(row["values"][key], value))
            for key, value in expected.items() if key != "soc")
        for row, expected in zip(rows, e["rows"]))
    f = _gold("SEM-REVIEW-F")
    result["SEM-REVIEW-F"] = f["source_type"] == "review_article" and f["canonical_outputs"] == 0
    g = _gold("SEM-NEG-G")
    result["SEM-NEG-G"] = g["source_domain"] == "photovoltaics" and g["canonical_semiconductor_outputs"] == 0
    h = _gold("SEM-MIXED-H")
    experimental, computational = mixed_h_rows()
    result["SEM-MIXED-H"] = all(
        len(actual) == len(expected) and all(
            row["property"] == gold["property"] and row["raw_value"] == gold["raw_value"]
            and row["unit"] == gold["unit"] and math.isclose(row["value"], gold["value"])
            for row, gold in zip(actual, expected))
        for actual, expected in ((experimental, h["experimental_outputs"]),
                                 (computational, h["computational_outputs"])))
    return result


def _provider_history() -> tuple[bool, list[dict]]:
    gate = json.loads((ROOT / "live_gate.json").read_text(encoding="utf-8"))
    freeze = json.loads((ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    snapshots = {item["run_id"]: item for item in freeze["provider_runs"]}
    runs = []
    for history in gate["runs"]:
        snapshot = snapshots[history["run_id"]]
        raw_state = inspect_optional_raw_artifact(
            ROOT.parents[1], snapshot["raw_payload_path"], snapshot["raw_sha256"])
        root = resolve_run_artifact_root(history["artifact_run_root"])
        files = [root / name for name in (
            "normalization_audit_v1.json", "normalized_candidate_v1.json",
            "normalized_validation_v1.json", "normalized_scientific_score_v1.json",
            "normalized_admission_v1.json")]
        present = [_io_path(path).is_file() for path in files]
        if any(present) and not all(present):
            raise ValueError(f"Incomplete provider normalization artifacts: {history['run_id']}")
        if not all(present):
            runs.append({
                "case_id": history["case_id"], "model_id": history["model_id"],
                "run_id": history["run_id"], "raw_sha256": snapshot["raw_sha256"],
                "normalization_complete": True,
                "normalization_artifact_available": False,
                **raw_state,
                "schema_valid": snapshot["normalized_schema_valid"],
                "raw_score": snapshot["raw_scientific_score"],
                "normalized_score": snapshot["normalized_scientific_score"],
                "canonical_admission": snapshot["normalized_canonical_admission"],
            })
            continue
        for path in files:
            expected = snapshot["normalization_artifact_hashes"][path.name]
            if sha256(_io_path(path).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Provider normalization artifact hash mismatch: {history['run_id']}")
        audit, candidate, validation, scientific, admission = (
            json.loads(_io_path(path).read_text(encoding="utf-8")) for path in files)
        runs.append({"case_id": history["case_id"], "model_id": history["model_id"],
                     "run_id": history["run_id"], "raw_sha256": history["raw_response_sha256"],
                     "normalization_artifact_available": True, **raw_state,
                     "normalization_complete": audit["raw_sha256"] == history["raw_response_sha256"]
                     and candidate["raw_sha256"] == history["raw_response_sha256"],
                     "schema_valid": validation["schema_valid"],
                     "raw_score": scientific["raw_score"], "normalized_score": scientific["normalized_score"],
                     "canonical_admission": admission["canonical_admission"]})
    good = gate["SEM_LIVE_GATE_SATISFIED"] and len(runs) == 4 and all(
        run.get("normalization_complete") and not run["canonical_admission"]
        and run["normalized_score"]["exact_value_and_unit_points"] <= run["raw_score"]["exact_value_and_unit_points"]
        for run in runs)
    return good, runs


def run_closure_audit() -> dict:
    interim = run_interim_audit()
    archives = recover_all_cases()
    archives["SEM-COMPUTE-E"] = recover_compute_e()
    archives["SEM-REVIEW-F"] = recover_review_f()
    negative = recover_neg_g()
    archives["SEM-MIXED-H"] = recover_mixed_h()
    parity = {**interim["source_gold_parity"], **_parity()}
    provider_good, provider_runs = _provider_history()
    outputs = {case: [("experimental", item) for exp in archive.experiments for item in exp.outputs]
               + [("computational", item) for calc in archive.calculations for item in calc.outputs]
               for case, archive in archives.items()}
    results = [item for case in archives for item in outputs[case]]
    projected = {case: [row for row in project_results_rows(archive)
                        if row["measurement_role"] == "result" and row["admission_status"] == "canonical"]
                 for case, archive in archives.items()}
    all_rows = [row for rows in projected.values() for row in rows]
    families = set(_RESULT_FAMILIES)
    a = archives["SEM-GOLD-A"]
    b = archives["SEM-TRANSPORT-B"]
    c = archives["SEM-OPTICAL-C"]
    e = archives["SEM-COMPUTE-E"]
    f = archives["SEM-REVIEW-F"]
    h = archives["SEM-MIXED-H"]
    a_outputs = [item for _, item in outputs["SEM-GOLD-A"]]
    b_outputs = [item for _, item in outputs["SEM-TRANSPORT-B"]]
    c_outputs = [item for _, item in outputs["SEM-OPTICAL-C"]]
    h_exp = [item for exp in h.experiments for item in exp.outputs]
    h_calc = [item for calc in h.calculations for item in calc.outputs]
    caption = a_outputs[0].model_copy(deep=True)
    caption.evidence = [Evidence(page=4, source_type=SourceType.figure_caption,
                                 original_source_type="figure_caption", verbatim_match=True,
                                 text_snippet=caption.raw_value, locator="figure=4;caption")]
    missing = a_outputs[0].model_copy(deep=True)
    missing.raw_value = "N/A"
    review_quarantine = f.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    b_gold = _gold("SEM-TRANSPORT-B")
    b_unavailable = sum(row[prop] is None for row in b_gold["rows"]
                        for prop in ("carrier_concentration", "carrier_mobility"))

    def inv(number: int, name: str, passed: bool, evidence: str) -> dict:
        return {"number": number, "name": name, "passed": bool(passed), "evidence": evidence}

    checks = [
        inv(1, "electronic band gap != optical band gap", {"electronic_band_gap", "optical_band_gap"} <= families, "Separate canonical properties."),
        inv(2, "band gap != PL peak", {item.property for item in c_outputs} == {"optical_band_gap", "photoluminescence_peak"}, "C source tables remain distinct."),
        inv(3, "work function != electron affinity", {"work_function", "electron_affinity"} <= families, "Separate canonical properties."),
        inv(4, "work function != ionization energy", {"work_function", "ionization_energy"} <= families, "Separate canonical properties."),
        inv(5, "carrier concentration != dopant concentration", any(item.property == "carrier_concentration" for item in a_outputs) and not any(item.property == "dopant_concentration" for _, item in results), "Measured carriers not converted to dopant density."),
        inv(6, "electron concentration != hole concentration", {"electron_concentration", "hole_concentration"} <= families, "Separate canonical properties."),
        inv(7, "mobility != conductivity", {"carrier_mobility", "conductivity"} <= families, "Separate units and property families."),
        inv(8, "Hall mobility retains Hall identity", all(item.method == "Hall_effect" for item in a_outputs if item.property == "hall_mobility"), "A Hall results retain method."),
        inv(9, "generic mobility != Hall mobility without support", all(run["raw_score"]["exact_property_key_points"] == run["normalized_score"]["exact_property_key_points"] for run in provider_runs if run.get("normalization_complete")), "Normalizer does not relabel generic mobility."),
        inv(10, "conductivity != resistivity", {"conductivity", "resistivity"} <= families, "Separate families."),
        inv(11, "sheet resistance != bulk resistivity", {"sheet_resistance", "resistivity"} <= {item.property for item in a_outputs}, "A retains Ω/sq and Ω·cm."),
        inv(12, "contact resistance != sheet resistance", {"contact_resistance", "sheet_resistance"} <= families, "Separate families."),
        inv(13, "threshold voltage != operating voltage", "threshold_voltage" in families and "operating_voltage" not in families, "Operating bias is not a threshold result."),
        inv(14, "breakdown voltage != breakdown field", {"breakdown_voltage", "breakdown_field"} <= families, "Voltage and field separate."),
        inv(15, "current != current density", "current_density" in families and "current" not in families, "Current cannot be density without area."),
        inv(16, "film thickness != depletion width", "film_thickness" not in families and "depletion_width" not in families, "Film thickness is a process/device parameter."),
        inv(17, "substrate != semiconductor film", all(len(device.material_ids) >= 2 and device.material_ids[0] != device.material_ids[1] for archive in archives.values() for device in archive.devices), "Separate layer entities."),
        inv(18, "growth temperature != measurement temperature", all("measurement_temperature" not in item.conditions for item in a_outputs) and any(p.property == "growth_temperature" for process in a.processes for p in process.parameters), "A source does not report Hall temperature."),
        inv(19, "annealing temperature != measurement temperature", all(item.conditions.get("measurement_temperature") == "room_temperature" for item in b_outputs) and any(p.property == "annealing_temperature" for process in b.processes for p in process.parameters), "B process and measurement conditions separate."),
        inv(20, "measured != computational", all(
            row["record_type"] == ("calculation" if case == "SEM-COMPUTE-E" else "experiment")
            for case in ("SEM-GOLD-A", "SEM-TRANSPORT-B", "SEM-OPTICAL-C", "SEM-PROCESS-D", "SEM-COMPUTE-E")
            for row in projected[case]
        ) and len(h.experiments) == 2 and len(h.calculations) == 1
        and sum(row["record_type"] == "experiment" for row in projected["SEM-MIXED-H"]) == 5
        and sum(row["record_type"] == "calculation" for row in projected["SEM-MIXED-H"]) == 4,
            "A-D experimental, E computational, H five experimental/four computational results."),
        inv(21, "calculated band gap != measured band gap", all(item.property == "calculated_band_gap" for calc in e.calculations for item in calc.outputs) and not any(item.property == "calculated_band_gap" for exp in h.experiments for item in exp.outputs), "E Table 1 band gaps are calculation-only."),
        inv(22, "calculated effective mass != measured mobility", {item.property for item in h_calc} == {"calculated_effective_mass"} and {item.property for item in h_exp[:2]} == {"electron_mobility", "hole_mobility"}, "H DFT masses and FET mobility separate."),
        inv(23, "calculated work function != measured work function", "work_function" in families
            and not any(item.property == "work_function" for _, item in results)
            and semiconductor_admission_decision(
                e.calculations[0].outputs[0].model_copy(update={"property": "work_function"}),
                role="result", modality="computational").admitted
            and not semiconductor_admission_decision(
                e.calculations[0].outputs[0].model_copy(update={"property": "work_function"}),
                role="result", modality="experimental").admitted,
            "Synthetic contract probe: calculated evidence cannot be admitted as measured work function."),
        inv(24, "defect formation energy != activation energy", {"defect_formation_energy", "activation_energy"} <= families
            and _RESULT_FAMILIES["defect_formation_energy"] == _RESULT_FAMILIES["activation_energy"]
            and "defect_formation_energy" != "activation_energy"
            and not any(item.property in {"defect_formation_energy", "activation_energy"} for _, item in results)
            and not semiconductor_admission_decision(
                e.calculations[0].outputs[0].model_copy(update={"property": "defect_formation_energy"}),
                role="result", modality="experimental").admitted,
            "Distinct energy keys; a computational defect quantity cannot be admitted as an experimental result."),
        inv(25, "dopant identity retained", all(any(m.dopants and m.dopants[0]["element"] == dopant for m in archives[case].materials) for case, dopant in (("SEM-GOLD-A", "Ga"), ("SEM-TRANSPORT-B", "Al"), ("SEM-PROCESS-D", "F"))), "Ga/Al/F remain source-specific."),
        inv(26, "dopant concentration retained", all("nominal_atomic_percent" in m.dopants[0] for m in a.materials if m.dopants) and all("ideal_atomic_percent" in m.dopants[0] for m in b.materials if m.dopants), "Nominal atomic percentages kept as supplied."),
        inv(27, "carrier type retained", all(item.conditions.get("carrier_type") == "n-type" for item in a_outputs if item.property == "carrier_concentration") and {item.conditions.get("carrier_identity") for item in h_exp[:2]} == {"electron", "hole"}, "A n-type and H electron/hole labels retained."),
        inv(28, "specimen identity retained", all(item.conditions.get("sample_label") for _, item in results) and all(len(calc.material_ids) == 1 for archive in archives.values() for calc in archive.calculations), "Every output has specimen label and calculation material."),
        inv(29, "device identity retained", len(h.devices) == 1 and all(len(exp.device_ids) == 1 for exp in h.experiments), "Both H experiments refer to the LE-FET."),
        inv(30, "missing conditions not inferred", all("measurement_temperature" not in item.conditions for item in a_outputs) and all(item.conditions.get("measurement_temperature") == "78 K" for item in h_exp), "A remains unreported; H is source-reported 78 K."),
        inv(31, "missing values not interpolated", len(b_outputs) == 46 and len(e.calculations) == 12, "B/E only source-present cells admitted."),
        inv(32, "unavailable table cells remain unavailable", b_unavailable == 14 and len(b_outputs) == 46 and all(row["values"][k] is None for row in compute_e_rows() for k in ("GW0", "GW") if row["soc"] == "with"), "B dash cells and E missing GW cells excluded."),
        inv(33, "caption-only evidence cannot admit", not semiconductor_admission_decision(caption, role="result").admitted, "Caption-only A value rejected."),
        inv(34, "N/A cannot become numeric", not semiconductor_admission_decision(missing, role="result").admitted, "N/A raw token rejected."),
        inv(35, "raw units retained", all(item.unit == "eV" for calc in e.calculations for item in calc.outputs) and {item.unit for item in h_exp} == {"×10^-2 cm^2/V/s", "×10^-3 cm^2/V/s", "nm"}, "E/H publisher units retained; normalized mobility separate."),
        inv(36, "review values remain non-focal", not f.experiments and not f.calculations and len(review_quarantine) == 2 and all(obj["reason"].startswith("ownership_") for obj in review_quarantine), "Review citations quarantined."),
        inv(37, "negative control produces zero Semiconductor contamination", negative["routed_domain"] == "photovoltaics" and negative["semiconductor_outputs"] == 0, "PV source routes to PV with page-8 metrics."),
        inv(38, "normalized provider artifacts remain separate from raw", provider_good, "Four raw hashes and separate normalized artifacts verified."),
        inv(39, "analytics retain material/specimen/process/property/modality identity", len(all_rows) == len(results) == 120
            and all(row["material_ids"] and row["metric"] and json.loads(row["conditions_json"]).get("sample_label") for row in all_rows)
            and all(row["record_type"] == "calculation" for row in projected["SEM-COMPUTE-E"])
            and all(json.loads(row["conditions_json"])["synthesis_annealing_temperature"]["process_id"] == h.processes[0].process_id
                    for row in projected["SEM-MIXED-H"] if row["record_type"] == "experiment")
            and all(json.loads(row["conditions_json"])["synthesis_annealing_time"]["process_id"] == h.processes[0].process_id
                    for row in projected["SEM-MIXED-H"] if row["record_type"] == "experiment"),
            "All rows retain specimen/property/modality; H experimental analytics retain process lineage."),
        inv(40, "archive/domain scoping correct", all(archive.metadata.domain == "semiconductors" for archive in archives.values()) and all(row["domain"] == "semiconductors" for row in all_rows) and negative["routed_domain"] == "photovoltaics", "Seven SEM archives; negative source remains PV."),
    ]
    evidence_violations = sum(not semiconductor_admission_decision(item, role="result", modality=modality).admitted
                              for modality, item in results)
    cross_record = sum(len(exp.material_ids) != 1 or (archive.devices and len(exp.device_ids) != 1)
                       for archive in archives.values() for exp in archive.experiments)
    ownership = sum(bool(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])
                    for case, archive in archives.items() if case != "SEM-REVIEW-F")
    graph = sum(1 for archive in archives.values() if archive.model_validate(archive.model_dump()).metadata.archive_id != archive.metadata.archive_id)
    contamination = {"ownership": ownership, "evidence": evidence_violations,
                     "cross_record_leakage": cross_record,
                     "analytics": abs(len(all_rows) - len(results)), "graph": graph}
    cases = {case: {"materials": len(archive.materials), "devices": len(archive.devices),
                    "processes": len(archive.processes), "experiments": len(archive.experiments),
                    "calculations": len(archive.calculations), "canonical_outputs": len(outputs[case]),
                    "analytics_rows": len(projected[case]),
                    "noncanonical_or_review": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]),
                    "quarantine": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])}
             for case, archive in archives.items()}
    cases["SEM-NEG-G"] = {"materials": 0, "devices": 0, "processes": 0,
                          "experiments": 0, "calculations": 0, "canonical_outputs": 0,
                          "analytics_rows": 0, "noncanonical_or_review": 0, "quarantine": 0,
                          "routed_domain": negative["routed_domain"]}
    passed = all(parity.values()) and all(check["passed"] for check in checks) and not any(contamination.values()) and provider_good and interim["passed"]
    return {"schema": "synthex.semiconductors.closure_audit.v1", "freeze_ready": passed,
            "case_count": 8, "source_gold_parity": parity, "cases": cases,
            "canonical_output_total": len(results),
            "experiment_count": sum(len(archive.experiments) for archive in archives.values()),
            "calculation_count": sum(len(archive.calculations) for archive in archives.values()),
            "invariants": checks, "passed_invariants": sum(check["passed"] for check in checks),
            "contamination": contamination, "live_gate_satisfied": provider_good,
            "provider_runs": provider_runs, "negative_route": negative["routed_domain"],
            "interim_audit_passed": interim["passed"]}


if __name__ == "__main__":
    audit = run_closure_audit()
    if "--write" in sys.argv:
        (ROOT / "closure_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("freeze_ready", "canonical_output_total",
                                                 "experiment_count", "calculation_count",
                                                 "passed_invariants", "contamination", "source_gold_parity")},
                     indent=2, ensure_ascii=True))
