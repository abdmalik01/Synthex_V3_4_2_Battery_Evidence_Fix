from __future__ import annotations

import json
from hashlib import sha256

import pytest

from benchmark.biomaterials_v1.analytics import analytics_rows
from benchmark.biomaterials_v1.build_archive import build_archive
from benchmark.biomaterials_v1.closure import audit
from benchmark.biomaterials_v1.offline_recovery import (
    ROOT, computational_method_e, formulations_h, negative_route_g, recover,
    review_cited_values_f,
)
from synthex_platform.extraction.biomaterials_contract import biomaterials_result_identity


def _gold(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_compute_e_exact_gold_method_and_calculation_separation():
    gold = _gold("gold_compute_e.json")
    rows = recover("BIO-COMPUTE-E")["outputs"]
    assert len(rows) == gold["gold_output_count"] == 32
    assert [(r["sample_label"], r["property"], r["value"]) for r in rows] == [
        (label, prop, value)
        for label, electrostatic, interaction in gold["rows"]
        for prop, value in (("electrostatic_interaction_energy", electrostatic),
                            ("interaction_energy", interaction))
    ]
    method = computational_method_e()
    assert method["code"] == "NAMD" and "CHARMM27" in method["force_field"]
    assert method["initial_relaxation_temperature_K"] == 310.6
    assert method["initial_relaxation_pressure_kPa"] == 101.3
    assert "3000 ps NPT at 1 fs" in method["production"]
    assert "27000 ps NVT at 2 fs" in method["production"]
    assert "periodic" in method["boundary"] and "TIP3P" in method["solvent"]
    archive = build_archive("BIO-COMPUTE-E")
    assert not archive.experiments and not archive.devices and not analytics_rows(archive)
    assert len(archive.calculations) == gold["expected_calculations"] == 16
    assert sum(len(item.outputs) for item in archive.calculations) == 32
    assert all(item.code == "NAMD" and item.model["system"] for item in archive.calculations)
    assert all(out.conditions["scientific_type"] == "calculated" for calc in archive.calculations for out in calc.outputs)


def test_review_f_dual_detection_and_cited_only_containment(monkeypatch):
    gold = _gold("gold_review_f.json")
    recovered = review_cited_values_f()
    assert recovered["publisher_review_signal"] and recovered["author_self_description"]
    assert [(r["label"], r["property"], r["value"]) for r in recovered["cited_values"]] == [
        (r["label"], r["property"], r["value"]) for r in gold["cited_rows"]]
    archive = build_archive("BIO-REVIEW-F")
    assert not archive.materials and not archive.devices and not archive.experiments and not archive.calculations
    assert not analytics_rows(archive)
    assert all(edge.predicate == "reported_by" for edge in archive.relationships)
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    assert len(quarantine) == 8
    assert all(item["ownership"] == "cited_prior_work" for item in quarantine)
    from benchmark.biomaterials_v1 import offline_recovery
    pages = offline_recovery._pages("BIO-REVIEW-F")
    monkeypatch.setattr(offline_recovery, "_pages", lambda case: [pages[0].replace("Review", "Article", 1), *pages[1:]])
    with pytest.raises(ValueError, match="independent publisher and author"):
        offline_recovery.review_cited_values_f()
    monkeypatch.setattr(offline_recovery, "_pages", lambda case: [pages[0].replace("we review", "we summarize", 1), *pages[1:]])
    with pytest.raises(ValueError, match="independent publisher and author"):
        offline_recovery.review_cited_values_f()


def test_negative_g_routes_to_battery_without_biomaterials_contamination():
    gold = _gold("gold_neg_g.json")
    routed = negative_route_g()
    assert routed["route"] == routed["repeat_route"] == gold["expected_route"] == "batteries"
    assert routed["stable"] and all(routed["misleading_vocabulary"].values())
    archive = build_archive("BIO-NEG-G")
    assert not archive.materials and not archive.devices and not archive.processes
    assert not archive.experiments and not archive.calculations and not analytics_rows(archive)
    assert all(edge.predicate == "reported_by" for edge in archive.relationships)


def test_mixed_h_formulation_specimens_process_rheology_and_biology():
    gold = _gold("gold_mixed_h.json")
    rows = recover("BIO-MIXED-H")["outputs"]
    assert len(rows) == 25
    formulations = formulations_h()
    assert {label: item["alginate_wv_percent"] for label, item in formulations.items()} == gold["alginate_wv_percent_by_sample"]
    archive = build_archive("BIO-MIXED-H")
    assert len(archive.materials) == 5 and len(archive.devices) == 10
    assert len(archive.processes) == 10 and len(archive.experiments) == 20
    assert not archive.calculations
    assert {d.configuration["specimen_type"] for d in archive.devices} == {"hydrogel", "scaffold"}
    assert sum(len(p.parameters) for p in archive.processes) == 5
    assert all(p.qualifier == "approx" for proc in archive.processes for p in proc.parameters)
    outputs = [out for exp in archive.experiments for out in exp.outputs]
    assert len(outputs) == 25
    visc = [out for out in outputs if out.property == "viscosity"]
    bio = [out for out in outputs if out.property == "cell_viability"]
    assert len(visc) == 10 and len(bio) == 15
    assert {out.conditions["shear_rate_per_s"] for out in visc} == {1, 100}
    assert all(out.conditions["specimen_type"] == "hydrogel" for out in visc)
    assert all(out.conditions["specimen_type"] == "scaffold" and out.conditions["cell_line"] == gold["biology"]["cell_line"] for out in bio)
    assert {out.conditions["exposure_time"] for out in bio} == {"immediately after printing", "day 4", "day 15"}
    assert len({(row["specimen_id"], row["identity"]) for row in analytics_rows(archive)}) == 25
    assert biomaterials_result_identity(visc[0]) != biomaterials_result_identity(visc[5])
    assert not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def test_eight_case_closure_and_provider_history_are_independent_of_live_gate():
    result = audit()
    assert result["DETERMINISTIC_BIOMATERIALS_V1_READY"] is True
    assert result["BIO_LIVE_GATE_SATISFIED"] is False
    assert result["invariant_count"] == result["invariant_pass_count"] == 40
    assert len(result["cases"]) == len(result["locks"]) == 8
    assert result["totals"] == {"canonical_outputs": 158, "experiments": 94, "calculations": 16}
    assert all(not values for values in result["contamination"].values())
    history = result["provider_history"]
    assert history["attempts"] == 16 and history["payloads"] == 0
    assert not history["BIO_BIOACT_B_sent"] and not history["BIO_LIVE_GATE_SATISFIED"]
    assert {item["exact_model"]: (item["attempts"], item["http_code"])
            for item in history["runs"]} == {
                "models/gemini-3.8-flash": (3, 503),
                "models/gemini-3.5-flash": (3, 503),
                "models/gemini-2.5-flash": (1, 404),
                "models/gemini-3.7-flash": (3, 503),
                "models/gemini-3.6-flash": (3, 503),
                "models/gemini-3.1-pro-preview": (3, 429),
            }
    assert all(item["scientific_score"] is None and not item["payload_returned"]
               and not item["RAW_PROVIDER_ARTIFACT_AVAILABLE"] for item in history["runs"])
    assert all("report_available_locally" not in item for item in history["runs"])


def test_fresh_candidate_selection_is_pinned_source_free_and_pending_approval():
    selected = _gold("candidate_selection.json")
    discovery = ROOT.parents[1] / selected["discovery_artifact"]
    if discovery.is_file():
        assert sha256(discovery.read_bytes()).hexdigest() == selected["discovery_sha256"]
        listing = json.loads(discovery.read_text(encoding="utf-8"))
        eligible = {item["model_id"] for item in listing["eligible_general_text_models"]}
    else:
        assert len(selected["discovery_sha256"]) == 64
        eligible = {item["model_id"] for item in selected["selected_exact_models"]}
    ids = [item["model_id"] for item in selected["selected_exact_models"]]
    assert len(ids) == len(set(ids)) == 3 and set(ids) <= eligible
    assert all("latest" not in model for model in ids)
    assert not set(ids) & set(selected["previous_provider_history"])
    assert selected["status_at_selection_time"] == "pending_fresh_authorization"
    assert selected["status"] == "historical_selection_completed_no_payload"
    assert selected["source_transmitted_by_discovery_or_selection"] is False
    assert selected["gold_will_be_transmitted"] is False
