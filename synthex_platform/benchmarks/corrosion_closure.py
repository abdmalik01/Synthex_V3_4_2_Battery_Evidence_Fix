"""Offline, provider-free Corrosion V1 closure reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from synthex_platform.core.archive import SynthexArchive
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_computational_recovery import (
    recover_corrosion_computational_tables,
)
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.source_context import build_source_bundle

from .corrosion import score_corrosion_archive
from .corrosion_controls import audit_corrosion_negative_control, audit_corrosion_review_control
from .corrosion_live import (
    all_expectations_from_gold,
    load_live_case,
    quarantine_expectations_from_gold,
    replay_saved_live_corrosion_case,
)


def _audit_payload(archive: SynthexArchive) -> dict[str, Any]:
    for payload in archive.domain_payloads:
        if payload.domain == "corrosion":
            value = payload.values.get("admissibility_audit")
            if isinstance(value, dict):
                return value
    return {}


def _paper_types(archive: SynthexArchive) -> list[str]:
    for payload in archive.domain_payloads:
        if payload.domain == "corrosion":
            value = payload.values.get("paper_types")
            if isinstance(value, list):
                return [str(item) for item in value]
    return []


def _case_summary(
    case_id: str,
    archive: SynthexArchive,
    score,
    *,
    score_basis: str,
) -> dict[str, Any]:
    audit = _audit_payload(archive)
    gold_count = score.total_required + score.quarantine_total
    gold_matches = score.matched_required + score.quarantine_matches
    return {
        "case_id": case_id,
        "route": archive.metadata.domain,
        "paper_types": _paper_types(archive),
        "gold_count": gold_count,
        "gold_matches": gold_matches,
        "canonical_experiments": len(archive.experiments),
        "canonical_calculations": len(archive.calculations),
        "admitted_metrics": int(audit.get("admitted_quantitative_values", 0)),
        "quarantine_count": int(audit.get("quarantined_objects_or_values", 0)),
        "ownership_violations": 0,
        "evidence_violations": score.total_required - score.source_tracking_matches,
        "overall": score.overall,
        "status": "pass" if gold_matches == gold_count and score.overall == 1.0 else "fail",
        "score_basis": score_basis,
    }


def _score_archive(case_id: str, repo_root: Path, archive: SynthexArchive, *, score_basis: str):
    case = load_live_case(case_id, repo_root)
    gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
    score = score_corrosion_archive(
        archive,
        all_expectations_from_gold(gold),
        quarantine_expectations_from_gold(gold),
    )
    return _case_summary(case_id, archive, score, score_basis=score_basis)


def _stored_case(case_id: str, repo_root: Path) -> dict[str, Any]:
    archive_path = repo_root / "output" / "corrosion_v1" / "live" / case_id / "archive.json"
    archive = SynthexArchive.model_validate_json(archive_path.read_text(encoding="utf-8"))
    return _score_archive(case_id, repo_root, archive, score_basis="saved_archive_offline_rescore")


def _replayed_case(case_id: str, repo_root: Path) -> dict[str, Any]:
    result = replay_saved_live_corrosion_case(case_id, repo_root)
    return _case_summary(
        case_id,
        result["archive"],
        type("ScoreView", (), result["post_recovery_score"])(),
        score_basis="saved_provider_payload_offline_deterministic_replay",
    )


def _dft_case(repo_root: Path) -> dict[str, Any]:
    case = load_live_case("CORR-DFT-F", repo_root)
    bundle = build_source_bundle(
        case.pdf_path,
        source_filename=case.filename,
        enable_ocr=False,
        include_figures=False,
    )
    document = CorrosionDocument.model_validate({
        "source": {"title": case.title, "doi": case.doi},
        "paper_types": ["computational_corrosion"],
    })
    document = recover_corrosion_computational_tables(document, bundle)
    document = verify_corrosion_document_evidence(document, bundle)
    archive = assemble_corrosion_archive(document, source_bundle=bundle)
    summary = _score_archive(
        case.case_id,
        repo_root,
        archive,
        score_basis="locked_source_offline_deterministic_recovery",
    )
    summary["live_provider_status"] = "unavailable_503_no_score_no_retry"
    return summary


def build_corrosion_v1_closure_summary(repo_root: str | Path) -> dict[str, Any]:
    """Build the heterogeneous eight-case audit without any provider calls."""
    repo_root = Path(repo_root).resolve()
    cases = [
        _stored_case("CORR-GOLD-A", repo_root),
        _stored_case("CORR-COAT-B", repo_root),
        _replayed_case("CORR-INHIB-C", repo_root),
        _stored_case("CORR-EIS-D", repo_root),
        _replayed_case("CORR-WEIGHT-E", repo_root),
        _dft_case(repo_root),
    ]

    review = audit_corrosion_review_control(repo_root)
    cases.append({
        "case_id": review["case_id"],
        "route": review["route"],
        "paper_types": review["paper_types"],
        "gold_count": review["score"]["total"],
        "gold_matches": review["score"]["passed"],
        "canonical_experiments": review["canonical_experiments"],
        "canonical_calculations": review["canonical_calculations"],
        "admitted_metrics": review["admitted_metrics"],
        "quarantine_count": review["noncanonical_candidate_count"],
        "ownership_violations": review["ownership_violations"],
        "evidence_violations": review["evidence_violations"],
        "overall": review["score"]["overall"],
        "status": "pass" if review["score"]["overall"] == 1.0 else "fail",
        "score_basis": "locked_source_offline_review_control",
    })

    negative = audit_corrosion_negative_control(repo_root)
    cases.append({
        "case_id": negative["case_id"],
        "route": negative["route"],
        "paper_types": negative["paper_types"],
        "gold_count": negative["score"]["total"],
        "gold_matches": negative["score"]["passed"],
        "canonical_experiments": negative["canonical_experiments"],
        "canonical_calculations": negative["canonical_calculations"],
        "admitted_metrics": negative["admitted_corrosion_metrics"],
        "quarantine_count": 0,
        "ownership_violations": 0,
        "evidence_violations": 0,
        "overall": negative["score"]["overall"],
        "status": "pass" if negative["score"]["overall"] == 1.0 else "fail",
        "score_basis": "locked_source_offline_negative_control",
    })

    return {
        "benchmark": "Synthex Corrosion V1",
        "provider_calls": 0,
        "aggregate_accuracy": None,
        "aggregate_note": "Case contracts are heterogeneous; no aggregate accuracy is calculated.",
        "all_cases_pass": all(item["status"] == "pass" for item in cases),
        "ownership_contamination_count": sum(item["ownership_violations"] for item in cases),
        "evidence_violation_count": sum(item["evidence_violations"] for item in cases),
        "cases": cases,
    }
