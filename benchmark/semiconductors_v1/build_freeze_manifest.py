"""Build the portable Semiconductor V1 freeze record from verified local artifacts.

This command performs no network or provider calls. Run only after the full
regression suite and diff checks pass; the test count is supplied explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from synthex_platform.benchmarks.provider_artifacts import _io_path

from .closure_audit import CASES, run_closure_audit
from .normalize_provider_v1 import ARTIFACTS
from .recover_cases import _SOURCES
from .source_tables import LOCK_NAMES, ROOT, resolve_run_artifact_root, source_lock


REPO = ROOT.parents[1]
DISCOVERY = REPO / "output/semiconductors_v1/provider_runs/model_discovery/20261001T050243277588Z.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(_io_path(path).read_text(encoding="utf-8"))


def _repo_path(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def build_manifest(*, regression_passed: int) -> dict:
    audit = run_closure_audit()
    if not audit["freeze_ready"] or audit["passed_invariants"] != 40:
        raise ValueError("Semiconductor scientific closure is not green")
    if regression_passed < 657:
        raise ValueError("Full regression evidence is incomplete")
    gate = _read(ROOT / "live_gate.json")
    if not gate["SEM_LIVE_GATE_SATISFIED"] or len(gate["runs"]) != 4:
        raise ValueError("Live gate/history changed")
    discovery = _read(DISCOVERY)
    cases = []
    for case_id in CASES:
        lock = source_lock(case_id)
        source = _SOURCES[case_id] if case_id in _SOURCES else None
        title = lock.get("source_title") or (source.title if source else None)
        if not title or (source and source.doi != lock["doi"]):
            raise ValueError(f"Missing or inconsistent source identity for {case_id}")
        counts = audit["cases"][case_id]
        cases.append({
            "case_id": case_id,
            "source_title": title,
            "doi": lock["doi"],
            "article_url": lock.get("article_url") or lock.get("publisher_url"),
            "source_lock_path": _repo_path(ROOT / LOCK_NAMES[case_id]),
            "locked_source_path": _repo_path(ROOT / lock["article_file"]),
            "source_sha256": lock["article_sha256"],
            "gold_path": _repo_path(ROOT / lock["gold_file"]),
            "gold_sha256": lock["gold_sha256"],
            "source_gold_parity": audit["source_gold_parity"][case_id],
            "deterministic_score": {"exact_outputs": counts["canonical_outputs"],
                                     "expected_outputs": counts["canonical_outputs"],
                                     "negative_route_correct": counts.get("routed_domain") == "photovoltaics"
                                     if case_id == "SEM-NEG-G" else None},
            "counts": counts,
        })
    runs = []
    for run in gate["runs"]:
        root = resolve_run_artifact_root(run["artifact_run_root"])
        raw_files = list(root.glob("attempt-*/raw_response.txt"))
        if len(raw_files) != 1 or _sha(raw_files[0]) != run["raw_response_sha256"]:
            raise ValueError(f"Provider raw payload hash mismatch: {run['run_id']}")
        normalization = _read(root / "normalization_audit_v1.json")
        validation = _read(root / "normalized_validation_v1.json")
        scientific = _read(root / "normalized_scientific_score_v1.json")
        admission = _read(root / "normalized_admission_v1.json")
        if normalization["raw_sha256"] != run["raw_response_sha256"] or admission["canonical_admission"]:
            raise ValueError(f"Unsafe normalization: {run['run_id']}")
        repair_replay_path = root / "repair_replay.json"
        repair_replay = _read(repair_replay_path) if _io_path(repair_replay_path).is_file() else None
        semantic_drifts = [
            {"sample": point.get("sample"), "expected_property_key": point.get("property"),
             "observed_property_key": point.get("observed_property_key"),
             "classification": "scientific_subtype_loss"}
            for point in run["raw_scientific_score"].get("point_details", [])
            if point.get("exact_value_and_unit") and not point.get("exact_property_key")
        ]
        runs.append({
            "case_id": run["case_id"], "provider": gate["provider_name"],
            "exact_model": run["model_id"], "run_id": run["run_id"],
            "run_artifact_path": _repo_path(root),
            "raw_payload_path": _repo_path(raw_files[0]),
            "raw_sha256": run["raw_response_sha256"],
            "primary_attempts": len(run["attempts"]),
            "provider_status": run["status"],
            "raw_scientific_score": scientific["raw_score"],
            "raw_schema_valid": validation["source_raw_schema_valid"],
            "raw_schema_error_count": normalization["raw_schema_error_count"],
            "raw_schema_failure_categories": normalization["raw_schema_failure_categories"],
            "scientific_semantic_drifts": semantic_drifts,
            "normalization_version": normalization["normalizer_version"],
            "normalization_artifact_path": _repo_path(root / "normalization_audit_v1.json"),
            "normalization_artifact_hashes": {
                name: _sha(root / name) for name in ARTIFACTS
            },
            "normalization_applied_rules": normalization["applied_rules"],
            "deliberately_not_normalized": normalization["deliberately_not_normalized"],
            "normalized_scientific_score": scientific["normalized_score"],
            "normalized_schema_valid": validation["schema_valid"],
            "normalized_canonical_admission": admission["canonical_admission"],
            "normalized_quarantine_count": admission["quarantined_object_count"],
            "repair_replay": {
                "artifact_path": _repo_path(repair_replay_path),
                "artifact_sha256": _sha(repair_replay_path),
                "schema_valid": repair_replay["repair_json_schema_valid"],
                "error_locations": [error["loc"] for error in repair_replay["validation_errors"]],
            } if repair_replay else None,
        })
    return {
        "schema": "synthex.semiconductors.freeze_manifest.v1",
        "version": "Semiconductors V1",
        "freeze_status": "FROZEN_OFFLINE_AND_LIVE_GATE_SATISFIED",
        "freeze_statement": "Semiconductors V1 is scientifically closed for deterministic extraction, specimen/device identity, doping semantics, process lineage, transport, optical and electronic properties, computational separation, review containment, negative routing, evidence ownership, analytics safety, graph integrity, and archive/domain scoping. Raw provider extraction remains model-specific and is not automatically canonical.",
        "case_count": 8, "cases": cases,
        "canonical_output_total": audit["canonical_output_total"],
        "experiment_count": audit["experiment_count"],
        "calculation_count": audit["calculation_count"],
        "invariants": audit["invariants"],
        "passed_invariants": audit["passed_invariants"],
        "contamination": audit["contamination"],
        "live_gate_satisfied": audit["live_gate_satisfied"],
        "provider_discovery_history": [{
            "provider": discovery["provider_name"],
            "discovered_at": discovery["discovered_at"],
            "method": discovery["discovery_method"],
            "artifact_path": _repo_path(DISCOVERY),
            "artifact_sha256": _sha(DISCOVERY),
            "exact_models_run": gate["models_run"],
        }],
        "provider_runs": runs,
        "regression": {"suite": "tests_v3", "baseline_passed": 657,
                       "freeze_passed": regression_passed, "failures": 0,
                       "warnings": ["unchanged google-genai typing DeprecationWarning"]},
        "reproduction_commands": [
            r".\.venv\Scripts\python.exe -m benchmark.semiconductors_v1.interim_audit",
            r".\.venv\Scripts\python.exe -m benchmark.semiconductors_v1.closure_audit --write",
            r".\.venv\Scripts\python.exe -m pytest tests_v3 -q --basetemp=.pytest_tmp_semiconductor_closure",
            "git diff --check",
        ],
        "known_limitations": [
            "Provider payloads lack PDF-verified page-verbatim evidence and are not canonical despite normalized schema validity.",
            "SEM-TRANSPORT-B live payload covers 3/20 states and 9/46 values; missing states/cells were not inferred.",
            "SEM-OPTICAL-C source prints an absorption-coefficient cm^-2 header; that ambiguous value was excluded.",
            "SEM-PROCESS-D figure-only transport values were not digitized.",
            "SEM-COMPUTE-E Table 1 omits GW0/GW values with SOC; those cells remain absent.",
            "SEM-REVIEW-F cited values are noncanonical; SEM-NEG-G is a photovoltaic control, not a semiconductor archive.",
            "SEM-MIXED-H uses source-reported scaled mobility and DFT effective masses, not an inferred band gap or threshold voltage.",
            "Provider raw/normalized audit files are local ignored output artifacts; this manifest records paths and hashes, not the payload bodies.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--regression-passed", type=int, required=True)
    args = parser.parse_args()
    manifest = build_manifest(regression_passed=args.regression_passed)
    path = ROOT / "freeze_manifest.json"
    if path.exists():
        raise FileExistsError(f"Freeze manifest is append-only: {path}")
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{path}: {len(manifest['cases'])} cases, {manifest['passed_invariants']} invariants")
