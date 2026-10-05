"""Eight-case offline closure and conservative historical-provider replay."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from benchmark.semiconductors_v1.closure_audit import CASES, run_closure_audit
from benchmark.semiconductors_v1 import closure_cases
from benchmark.semiconductors_v1.closure_cases import (
    compute_e_rows, mixed_h_rows, recover_compute_e, recover_mixed_h,
    recover_neg_g, recover_review_f,
)
from benchmark.semiconductors_v1.normalize_provider_v1 import ARTIFACTS, normalize_raw
from benchmark.semiconductors_v1 import source_tables
from benchmark.semiconductors_v1.source_tables import ROOT, resolve_run_artifact_root, source_lock
from synthex_platform.benchmarks.provider_artifacts import _io_path
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import ExtractedDocument


@pytest.fixture(scope="module")
def closure():
    return run_closure_audit()


def test_all_eight_source_gold_locks_verify():
    assert len(CASES) == 8
    for case in CASES:
        lock = source_lock(case)
        assert lock["case_id"] == case
        assert lock["doi"]
        assert (ROOT / lock["article_file"]).is_file()


def test_live_gate_artifact_paths_are_portable_and_confined(tmp_path, monkeypatch):
    gate = json.loads((ROOT / "live_gate.json").read_text(encoding="utf-8"))
    assert len(gate["runs"]) == 4
    relative_paths = [run["artifact_run_root"] for run in gate["runs"]]
    assert all(path.startswith("output/semiconductors_v1/provider_runs/") for path in relative_paths)
    assert all(resolve_run_artifact_root(path).is_relative_to(ROOT.parents[1]) for path in relative_paths)
    moved_root = tmp_path / "another-checkout" / "benchmark" / "semiconductors_v1"
    monkeypatch.setattr(source_tables, "ROOT", moved_root)
    assert all(resolve_run_artifact_root(path).is_relative_to(tmp_path / "another-checkout") for path in relative_paths)
    with pytest.raises(ValueError, match="repository-relative"):
        resolve_run_artifact_root("C:\\Users\\someone\\output\\run")
    with pytest.raises(ValueError, match="repository-relative"):
        resolve_run_artifact_root("../outside")


def test_compute_e_uses_pdf_table_and_calculation_records():
    rows = compute_e_rows()
    assert rows[0]["values"]["PBE"] == 0.10
    assert rows[1]["values"]["GW0"] is None
    archive = recover_compute_e()
    assert not archive.experiments
    assert len(archive.calculations) == 12
    assert all(output.property == "calculated_band_gap" for item in archive.calculations for output in item.outputs)


def test_review_f_is_nonfocal():
    archive = recover_review_f()
    assert not archive.experiments and not archive.calculations
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    assert len(quarantine) == 2
    assert {entry["ownership"] for entry in quarantine} == {"review_summary", "cited_prior_work"}


@pytest.mark.parametrize("first_page", [
    "REVIEW ARTICLE without the authors' own review description",
    "the review presented here without a publisher article-type label",
])
def test_review_f_requires_both_independent_review_signals(monkeypatch, first_page):
    monkeypatch.setattr(closure_cases, "page_text", lambda _case, _page: first_page)
    with pytest.raises(ValueError, match="independent publisher and author review signals"):
        recover_review_f()


def test_negative_g_routes_to_photovoltaics_only():
    result = recover_neg_g()
    assert result["routed_domain"] == "photovoltaics"
    assert result["semiconductor_archives"] == result["semiconductor_outputs"] == 0


def test_mixed_h_keeps_experiments_and_dft_apart():
    experimental, computational = mixed_h_rows()
    assert len(experimental) == 5 and len(computational) == 4
    archive = recover_mixed_h()
    assert len(archive.devices) == len(archive.processes) == len(archive.calculations) == 1
    assert len(archive.experiments) == 2
    assert {output.property for exp in archive.experiments for output in exp.outputs} == {
        "electron_mobility", "hole_mobility", "emission_wavelength"}
    assert {output.property for calc in archive.calculations for output in calc.outputs} == {
        "calculated_effective_mass"}


def test_closure_has_40_real_checks_and_zero_contamination(closure):
    assert closure["case_count"] == 8
    assert [item["number"] for item in closure["invariants"]] == list(range(1, 41))
    assert closure["passed_invariants"] == 40
    assert all(closure["source_gold_parity"].values())
    assert closure["canonical_output_total"] == 120
    assert closure["contamination"] == {
        "ownership": 0, "evidence": 0, "cross_record_leakage": 0,
        "analytics": 0, "graph": 0}
    assert closure["freeze_ready"]


def test_normalizer_does_not_equate_scientifically_distinct_properties():
    raw = {"materials": [{"local_id": "sample-1", "name": "ZnO", "chemical_formula": "ZnO",
                          "ownership": "focal_work"}],
           "experiments": [{"local_id": "exp-1", "type": "transport", "material_refs": ["sample-1"],
                            "ownership": "focal_work"}],
           "measurements": [
               {"property_key": "carrier_mobility", "raw_value": "4.2", "unit": "cm^2/V/s",
                "material_ref": "sample-1", "experiment_ref": "exp-1"},
               {"property_key": "electron_concentration", "raw_value": "3.1", "unit": "cm^-3",
                "material_ref": "sample-1", "experiment_ref": "exp-1"},
               {"property_key": "hall_mobility", "raw_value": "2.0", "unit": "cm^2/V/s",
                "material_ref": "sample-1", "experiment_ref": "exp-1"},
               {"property_key": "carrier_concentration", "raw_value": "-", "unit": "cm^-3",
                "material_ref": "sample-1", "experiment_ref": "exp-1"}]}
    before = json.loads(json.dumps(raw))
    draft, scoring_view, _ = normalize_raw(raw)
    parsed = ExtractedDocument.model_validate(draft)
    props = [item.property for item in parsed.experiments[0].outputs]
    assert props == ["carrier_mobility", "electron_concentration", "hall_mobility", "carrier_concentration"]
    assert scoring_view["measurements"][0]["property"] == "carrier_mobility"
    assert parsed.experiments[0].outputs[-1].value is None
    assert all("measurement_temperature" not in item.conditions for item in parsed.experiments[0].outputs)
    assert all(item.evidence == [] for item in parsed.experiments[0].outputs)
    assert parsed.experiments[0].material_refs == ["sample-1"]
    assert parsed.experiments[0].outputs[0].conditions["provider_material_ref"] == "sample-1"
    assert parsed.experiments[0].outputs[0].conditions["provider_experiment_ref"] == "exp-1"
    assert raw == before
    archive = assemble_archive(parsed, domain="semiconductors", model="normalizer_safety_test")
    assert not archive.experiments


def test_normalizer_preserves_explicit_process_state_and_does_not_invent_ownership():
    raw = {
        "materials": [{"local_id": "film-1", "name": "ZnO film"}],
        "processes": [{"local_id": "anneal-1", "process_type": "annealing",
                       "output_material_refs": ["film-1"],
                       "parameters": [{"property_key": "annealing_temperature", "raw_value": "450",
                                       "unit": "C", "process_ref": "anneal-1"}]}],
        "experiments": [{"local_id": "hall-1", "type": "Hall measurement",
                         "material_refs": ["film-1"]}],
        "measurements": [{"property_key": "carrier_mobility", "raw_value": "21.4",
                          "unit": "cm^2/V/s", "material_ref": "film-1",
                          "process_ref": "anneal-1", "experiment_ref": "hall-1"}],
    }
    draft, _, _ = normalize_raw(raw)
    parsed = ExtractedDocument.model_validate(draft)
    assert parsed.materials[0].ownership == "unknown"
    assert parsed.processes[0].ownership == "unknown"
    assert parsed.processes[0].output_material_refs == ["film-1"]
    assert parsed.processes[0].parameters[0].conditions["provider_process_ref"] == "anneal-1"
    assert parsed.experiments[0].outputs[0].conditions["provider_process_ref"] == "anneal-1"
    assert parsed.experiments[0].outputs[0].conditions["provider_material_ref"] == "film-1"
    assert "measurement_temperature" not in parsed.experiments[0].outputs[0].conditions


def test_four_normalized_runs_are_append_only_and_independently_scored(closure):
    gate = json.loads((ROOT / "live_gate.json").read_text(encoding="utf-8"))
    freeze = json.loads((ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    snapshots = {item["run_id"]: item for item in freeze["provider_runs"]}
    assert gate["SEM_LIVE_GATE_SATISFIED"]
    assert len(closure["provider_runs"]) == len(gate["runs"]) == 4
    for history, normalized in zip(gate["runs"], closure["provider_runs"]):
        snapshot = snapshots[history["run_id"]]
        root = Path(history["artifact_run_root"])
        if not normalized["RAW_PROVIDER_ARTIFACT_AVAILABLE"]:
            assert not normalized["normalization_artifact_available"]
            assert normalized["raw_sha256"] == snapshot["raw_sha256"]
            assert normalized["raw_score"] == snapshot["raw_scientific_score"]
            assert normalized["normalized_score"] == snapshot["normalized_scientific_score"]
            assert normalized["canonical_admission"] == snapshot["normalized_canonical_admission"]
            continue
        assert all(_io_path(root / name).is_file() for name in ARTIFACTS)
        attempt = next(root / f"attempt-{n}" for n in range(1, 4)
                       if _io_path(root / f"attempt-{n}" / "raw_response.txt").is_file())
        raw_hash = sha256(_io_path(attempt / "raw_response.txt").read_bytes()).hexdigest()
        assert raw_hash == history["raw_response_sha256"] == normalized["raw_sha256"]
        assert normalized["schema_valid"]
        assert not normalized["canonical_admission"]
        assert normalized["raw_score"]["exact_value_and_unit_points"] == normalized["normalized_score"]["exact_value_and_unit_points"]
        assert normalized["raw_score"]["exact_property_key_points"] == normalized["normalized_score"]["exact_property_key_points"]
        assert normalized["normalized_score"]["page_locator_points"] == 0
        candidate = json.loads(_io_path(root / "normalized_candidate_v1.json").read_text(encoding="utf-8"))
        assert candidate["raw_sha256"] == raw_hash
        assert candidate["draft"] != json.loads(_io_path(attempt / "parsed_response.json").read_text(encoding="utf-8"))


def test_transport_b_repair_replay_records_seven_specific_schema_errors():
    gate = json.loads((ROOT / "live_gate.json").read_text(encoding="utf-8"))
    history = next(run for run in gate["runs"] if run["case_id"] == "SEM-TRANSPORT-B")
    root = Path(history["artifact_run_root"])
    expected_locations = {
        ("source", "journal"), ("source", "volume"), ("source", "issue"),
        ("source", "pages"), ("source", "publisher"), ("source", "evidence"),
        ("domain_values",)}
    replay_path = _io_path(root / "repair_replay.json")
    if replay_path.is_file():
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        repair_body = _io_path(root / "attempt-1" / "repair_response.txt").read_bytes()
        assert sha256(repair_body).hexdigest() == replay["repair_response_sha256"]
        assert not replay["repair_json_schema_valid"] and len(replay["validation_errors"]) == 7
        assert {tuple(error["loc"]) for error in replay["validation_errors"]} == expected_locations
    else:
        freeze = json.loads((ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
        snapshot = next(item for item in freeze["provider_runs"] if item["run_id"] == history["run_id"])
        assert not snapshot["repair_replay"]["schema_valid"]
        assert {tuple(loc) for loc in snapshot["repair_replay"]["error_locations"]} == expected_locations
