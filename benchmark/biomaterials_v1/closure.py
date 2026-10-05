"""Eight-case, source-locked Biomaterials V1 deterministic closure and live-history audit.

This command reads publisher PDFs, frozen gold, canonical archives, and persisted
provider metadata. It never constructs a provider client or sends source content.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.extraction.biomaterials_contract import (
    biomaterials_admission_decision, biomaterials_result_identity,
)

from .analytics import analytics_rows
from .build_archive import build_archive
from .offline_recovery import LOCKS, ROOT, negative_route_g, recover, review_cited_values_f

REPO = ROOT.parents[1]
PROVIDER_ROOT = REPO / "output/biomaterials_v1/provider_runs"
HISTORY = REPO / "benchmark/provider_audit/provider_history.json"
PILOT = ("BIO-GOLD-A", "BIO-BIOACT-B", "BIO-DEGR-C", "BIO-PROCESS-D")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _point(label: str, prop: str, value: float) -> tuple:
    return (label, prop, float(value))


def _expected(gold: dict) -> Counter:
    case = gold["case_id"]
    points = []
    if case == "BIO-GOLD-A":
        for item in gold["variants"]:
            label = item["label"]
            points.extend((_point(label, "pore_size", item["measured_pore_size_um"]),
                           _point(label, "volume_porosity", item["volume_porosity_percent"])))
            points.extend(_point(label, "cell_viability", value) for value in item["viability_percent"])
            points.extend(_point(label, "cell_proliferation_ratio", value) for value in item["proliferation_ratio"])
    elif case == "BIO-BIOACT-B":
        points = [_point(item["label"], "inhibition_zone", value)
                  for item in gold["variants"] for value in item["values"] if value is not None]
    elif case == "BIO-DEGR-C":
        mapping = {"swelling_percent": "swelling_ratio", "mass_loss_percent": "mass_loss",
                   "strut_diameter_um": "strut_diameter", "pore_diameter_um": "pore_diameter",
                   "compressive_yield_strength_MPa": "compressive_yield_strength",
                   "elastic_modulus_kPa": "elastic_modulus"}
        points = [_point(item["label"], prop, item[field]) for item in gold["variants"]
                  for field, prop in mapping.items()]
    elif case == "BIO-PROCESS-D":
        for item in gold["filament_dsc_table2"]:
            points.extend((_point(item["label"], "cold_crystallization_temperature", item["Tcc_C"]),
                           _point(item["label"], "melting_enthalpy", item["enthalpy_J_g"]),
                           _point(item["label"], "crystallinity", item["crystallinity_percent"])))
        for item in gold["scaffold_results"]:
            points.extend((_point(item["label"], "deposited_layer_width", item["deposited_layer_width_um"]),
                           _point(item["label"], "compressive_modulus", item["compressive_modulus_MPa"]),
                           _point(item["label"], "ultimate_compressive_strength", item["ultimate_compressive_strength_MPa"])))
    elif case == "BIO-COMPUTE-E":
        for label, electrostatic, interaction in gold["rows"]:
            points.extend((_point(label, "electrostatic_interaction_energy", electrostatic),
                           _point(label, "interaction_energy", interaction)))
    elif case == "BIO-MIXED-H":
        for index in range(5):
            label = f"S{index+1}"
            points.extend((_point(label, "viscosity", gold["rheology"]["viscosity_Pa_s_at_1_per_s"][index]),
                           _point(label, "viscosity", gold["rheology"]["viscosity_Pa_s_at_100_per_s"][index])))
            for key in ("viability_percent_immediate", "viability_percent_day_4", "viability_percent_day_15"):
                points.append(_point(label, "cell_viability", gold["biology"][key][index]))
    return Counter(points)


def _measurement(prop: str = "cell_viability", **context) -> Measurement:
    conditions = {"sample_label": "sample A", "cell_line": "C3A", "assay": "MTT",
                  "exposure_time": "24 h", "scientific_type": "reported_measurement", **context}
    return Measurement(property=prop, raw_value="90", value=90, unit="%", method=conditions.get("assay"),
        conditions=conditions, evidence=[Evidence(page=2, source_type=SourceType.table,
            table_id="Table 1", locator="sample A", text_snippet="sample A 90", verbatim_match=True)])


def _provider_history() -> dict:
    rows = [item for item in json.loads(HISTORY.read_text(encoding="utf-8"))["runs"]
            if item.get("domain") == "biomaterials"]
    expected = {
        "models/gemini-3.8-flash": (3, "TRANSIENT_UNAVAILABLE", 503),
        "models/gemini-3.5-flash": (3, "TRANSIENT_UNAVAILABLE", 503),
        "models/gemini-2.5-flash": (1, "INVALID_REQUEST", 404),
        "models/gemini-3.7-flash": (3, "TRANSIENT_UNAVAILABLE", 503),
        "models/gemini-3.6-flash": (3, "TRANSIENT_UNAVAILABLE", 503),
        "models/gemini-3.1-pro-preview": (3, "RATE_LIMITED", 429),
    }
    audits = []
    lock = LOCKS["BIO-GOLD-A"]
    for model, (count, error_class, code) in expected.items():
        matching = [item for item in rows if item["exact_model"] == model]
        if len(matching) != 1:
            raise ValueError(f"Biomaterials provider history expected one run for {model}")
        item = matching[0]
        path = REPO / "output" / item["report_path"]
        identity = item["source_gold_lock_identity"]
        if (item["attempt_count"] != count or item["provider_error_classes"] != [error_class]
                or identity.get("article_sha256") != lock["pdf_sha256"]
                or identity.get("gold_sha256") != lock["gold_sha256"]
                or item["payload_returned"] or item["raw_scientific_score"] is not None
                or item["schema_valid"] is not None or item["canonical_admission"] is not None
                or item["raw_artifacts"] or item["live_gate_qualifying"] is not False):
            raise ValueError(f"No-payload status changed: {model}")
        if path.is_file():
            if _sha(path) != item["report_sha256"]:
                raise ValueError(f"Provider report hash mismatch: {model}")
            report = json.loads(path.read_text(encoding="utf-8"))
            if (len(report["attempts"]) != count
                    or report["scientific_score_status"] != "NO_PAYLOAD"
                    or any(attempt["payload_returned"] for attempt in report["attempts"])
                    or list(path.parent.glob("attempt-*/raw_response*"))):
                raise ValueError(f"Provider report contradicts no-payload history: {model}")
        audits.append({"exact_model": model, "attempts": count, "http_code": int(code),
                       "payload_returned": False, "scientific_score": None,
                       "canonical_admission": None, "fallback_used": False,
                       "report_sha256": item["report_sha256"], "run_id": item["run_id"],
                       "RAW_PROVIDER_ARTIFACT_AVAILABLE": False})
    b_sent = any(item.get("case") == "BIO-BIOACT-B" for item in rows) or any(
        (PROVIDER_ROOT / "BIO-BIOACT-B").rglob("request_metadata.json"))
    if b_sent:
        raise ValueError("BIO-BIOACT-B unexpectedly transmitted")
    return {"runs": audits, "attempts": sum(item["attempts"] for item in audits),
            "payloads": 0, "BIO_BIOACT_B_sent": False, "BIO_LIVE_GATE_SATISFIED": False}


def audit() -> dict:
    locks = []
    golds = {}
    archives = {}
    cases = []
    evidence_violations = []
    ownership_contamination = []
    cross_record_leakage = []
    analytics_contamination = []
    graph_contamination = []
    for case, lock in LOCKS.items():
        source = (ROOT / lock["pdf"]).resolve()
        gold_path = (ROOT / lock["gold"]).resolve()
        source_ok = source.is_file() and _sha(source) == lock["pdf_sha256"]
        gold_ok = gold_path.is_file() and _sha(gold_path) == lock["gold_sha256"]
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        if not (source_ok and gold_ok and gold["doi"] == lock["doi"] and gold["source_pdf"] == lock["pdf"]):
            raise ValueError(f"Source/gold identity lock mismatch: {case}")
        locks.append({"case_id": case, "source": source.relative_to(REPO).as_posix(), "doi": lock["doi"],
                      "source_sha256": lock["pdf_sha256"], "gold": gold_path.relative_to(REPO).as_posix(),
                      "gold_sha256": lock["gold_sha256"], "verified": True})
        golds[case] = gold
        rows = recover(case)["outputs"]
        observed = Counter(_point(row["sample_label"], row["property"], row["value"]) for row in rows)
        expected = _expected(gold)
        if observed != expected or len(rows) != gold["gold_output_count"]:
            raise ValueError(f"Offline scientific gold mismatch: {case}")
        archive = build_archive(case)
        archives[case] = archive
        outputs = [m for exp in archive.experiments for m in exp.outputs] + [m for calc in archive.calculations for m in calc.outputs]
        canonical = Counter(_point(m.conditions["sample_label"], m.property, m.value) for m in outputs)
        if canonical != expected:
            raise ValueError(f"Canonical outputs differ from gold: {case}")
        if archive.sources[0].doi != lock["doi"] or archive.metadata.domain != "biomaterials":
            raise ValueError(f"Archive scope/source mismatch: {case}")
        for output in outputs:
            evidence = output.evidence[0] if output.evidence else None
            if not evidence or not evidence.page or not evidence.verbatim_match or output.raw_value not in (evidence.text_snippet or ""):
                evidence_violations.append(case)
        if case in {"BIO-REVIEW-F", "BIO-NEG-G"}:
            if archive.materials or archive.devices or archive.processes or archive.experiments or archive.calculations:
                ownership_contamination.append(case)
            if any(r.predicate != "reported_by" for r in archive.relationships):
                graph_contamination.append(case)
        if case == "BIO-COMPUTE-E" and (archive.experiments or len(archive.calculations) != 16):
            cross_record_leakage.append(case)
        if case != "BIO-COMPUTE-E" and archive.calculations:
            cross_record_leakage.append(case)
        analytics = analytics_rows(archive)
        if len(analytics) != sum(len(exp.outputs) for exp in archive.experiments):
            analytics_contamination.append(case)
        cases.append({"case_id": case, "gold_outputs": gold["gold_output_count"],
                      "matched_outputs": sum(observed.values()), "offline_score": 1.0,
                      "materials": len(archive.materials), "specimens": len(archive.devices),
                      "processes": len(archive.processes), "experiments": len(archive.experiments),
                      "calculations": len(archive.calculations), "analytics_rows": len(analytics),
                      "quarantined_objects": len(archive.domain_payloads[0].values["admissibility"]["quarantined_objects"])})
    a, b, c, d, e, f, g, h = (archives[case] for case in LOCKS)
    all_exp = [m for arc in archives.values() for exp in arc.experiments for m in exp.outputs]
    h_rows = analytics_rows(h)
    identity = lambda prop, **kw: biomaterials_result_identity(_measurement(prop, **kw))
    distinct = lambda left, right: identity(left) != identity(right)
    caption = _measurement()
    caption.evidence[0].source_type = SourceType.figure_caption
    missing = _measurement(cell_line=None)
    na = _measurement()
    na.raw_value = "N/A"
    simulated = _measurement("elastic_modulus", scientific_type="calculated")
    simulated.unit = "MPa"
    reviews = review_cited_values_f()
    route = negative_route_g()
    f_quarantine = f.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    checks = {
        1: distinct("cell_viability", "cell_proliferation_ratio"),
        2: distinct("cell_viability", "cytotoxicity"),
        3: distinct("cell_viability", "metabolic_activity"),
        4: identity("cell_viability", assay="MTT") != identity("cell_viability", assay="CCK-8"),
        5: identity("cell_viability", cell_line="C3A") != identity("cell_viability", cell_line="L929"),
        6: identity("inhibition_zone", organism="E. coli", strain="ATCC 25922") != identity("inhibition_zone", organism="S. aureus", strain="ATCC 29213"),
        7: identity("cell_viability", exposure_time="24 h") != identity("cell_viability", exposure_time="72 h"),
        8: distinct("hemolysis", "cell_viability"),
        9: distinct("inhibition_zone", "bacterial_viability"),
        10: distinct("cfu_reduction", "bacterial_viability"),
        11: distinct("cfu_reduction", "log_reduction"),
        12: not biomaterials_admission_decision(_measurement("bactericidal"), role="result").admitted and not biomaterials_admission_decision(_measurement("bacteriostatic"), role="result").admitted,
        13: distinct("mass_loss", "degradation_rate") and all(m.property != "degradation_rate" for m in all_exp if m.conditions.get("sample_label", "").startswith("Cs-Crg")),
        14: distinct("swelling_ratio", "water_uptake"),
        15: distinct("water_uptake", "porosity"),
        16: identity("mass_loss", exposure_time="28 day") != identity("mass_loss", exposure_time="72 h"),
        17: distinct("initial_mass", "final_mass"),
        18: distinct("porosity", "pore_size"),
        19: distinct("pore_size", "fiber_diameter"),
        20: distinct("contact_angle", "surface_roughness"),
        21: all(dev.device_id not in {mat.material_id for mat in arc.materials} for arc in archives.values() for dev in arc.devices),
        22: all(mat.material_id not in {dev.device_id for dev in arc.devices} for arc in archives.values() for mat in arc.materials),
        23: all(m.conditions.get("assay") for m in all_exp if m.property.startswith("cell_")),
        24: all(m.conditions.get("cell_line") for m in all_exp if m.property.startswith("cell_")),
        25: all(m.conditions.get("organism") and m.conditions.get("strain") for m in all_exp if m.property == "inhibition_zone"),
        26: all(m.conditions.get("exposure_time") for m in all_exp if m.property in {"cell_viability", "cell_proliferation_ratio", "swelling_ratio", "mass_loss"}),
        27: len(h.materials) == 5 and len({dev.configuration.get("alginate_wv_percent") for dev in h.devices}) == 5,
        28: len({proc.name for proc in a.processes}) == 2 and sum(bool(proc.parameters) for proc in h.processes) == 5,
        29: all(m.conditions.get("positive_control_mm") and m.conditions.get("negative_control_status") for m in all_exp if m.property == "inhibition_zone"),
        30: len(e.calculations) == 16 and not e.experiments and all(m.conditions.get("scientific_type") == "calculated" for calc in e.calculations for m in calc.outputs),
        31: not any(m.property.startswith("cell_") for calc in e.calculations for m in calc.outputs),
        32: not biomaterials_admission_decision(simulated, role="result", modality="computational").admitted,
        33: not biomaterials_admission_decision(missing, role="result").admitted and all("exposure_time" not in m.conditions for exp in b.experiments for m in exp.outputs),
        34: all(m.conditions.get("exposure_time") in {"72 h", "28 day"} for exp in c.experiments for m in exp.outputs if m.property in {"swelling_ratio", "mass_loss"}),
        35: not biomaterials_admission_decision(caption, role="result").admitted,
        36: not biomaterials_admission_decision(na, role="result").admitted,
        37: reviews["publisher_review_signal"] and reviews["author_self_description"] and len(reviews["cited_values"]) == 4 and len(f_quarantine) == 8 and not f.experiments and not f.calculations,
        38: route["route"] == "batteries" and route["stable"] and not g.experiments and not g.calculations and len(analytics_rows(g)) == 0,
        39: len({(row["specimen_id"], row["identity"]) for row in h_rows}) == 25 and len(h_rows) == 25 and len(analytics_rows(e)) == 0,
        40: len(archives) == 8 and all(arc.metadata.domain == "biomaterials" and len(arc.sources) == 1 for arc in archives.values()),
    }
    if len(checks) != 40 or not all(checks.values()):
        raise ValueError(f"Biomaterials invariants failed: {[n for n, ok in checks.items() if not ok]}")
    provider = _provider_history()
    failures = {"ownership_contamination": ownership_contamination, "evidence_violations": evidence_violations,
                "cross_record_leakage": cross_record_leakage, "analytics_contamination": analytics_contamination,
                "graph_contamination": graph_contamination}
    ready = all(not values for values in failures.values()) and all(checks.values()) and len(cases) == 8
    return {"status": "deterministic_ready_pending_live_gate" if ready else "deterministic_failed",
            "scientific_status": "deterministically_closed" if ready else "deterministic_failed",
            "freeze_status": "pending_live_provider_gate", "provider_payload_received": False,
            "DETERMINISTIC_BIOMATERIALS_V1_READY": ready, "BIO_LIVE_GATE_SATISFIED": False,
            "locks": locks, "cases": cases,
            "totals": {"canonical_outputs": sum(item["matched_outputs"] for item in cases),
                       "experiments": sum(item["experiments"] for item in cases),
                       "calculations": sum(item["calculations"] for item in cases)},
            "invariants": {str(number): passed for number, passed in checks.items()},
            "invariant_count": len(checks), "invariant_pass_count": sum(checks.values()),
            "contamination": failures, "provider_history": provider,
            "limitations": ["Frozen gold covers selected exact source values, not all figures or outcomes.",
                            "H source prints line-width unit as mm; those values are excluded, not silently corrected.",
                            "H source reports no exact degradation/swelling endpoint in the selected passages.",
                            "No Biomaterials provider payload exists; live scientific scoring remains N/A."]}


def main() -> int:
    result = audit()
    closure_path = ROOT / "closure_audit.json"
    closure_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    freeze = {"domain": "biomaterials", "version": "v1", "status": "pending_live_gate",
              "scientific_status": "deterministically_closed",
              "freeze_status": "pending_live_provider_gate", "provider_payload_received": False,
              "DETERMINISTIC_BIOMATERIALS_V1_READY": result["DETERMINISTIC_BIOMATERIALS_V1_READY"],
              "BIO_LIVE_GATE_SATISFIED": False, "closure_audit": closure_path.name,
              "source_gold_locks": "source_locks.json", "freeze_commit_created": False,
              "historical_candidate_selection": "candidate_selection.json",
              "provider_history": "../provider_audit/provider_history.json",
              "reproduction": ["python -m benchmark.biomaterials_v1.closure",
                               "python -m pytest tests_v3 -q --basetemp=.pytest_tmp"],
              "known_limitations": result["limitations"]}
    (ROOT / "draft_freeze_manifest.json").write_text(json.dumps(freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"closure_audit": str(closure_path), "ready": result["DETERMINISTIC_BIOMATERIALS_V1_READY"],
                      "invariants_passed": result["invariant_pass_count"], "totals": result["totals"]}))
    return 0 if result["DETERMINISTIC_BIOMATERIALS_V1_READY"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
