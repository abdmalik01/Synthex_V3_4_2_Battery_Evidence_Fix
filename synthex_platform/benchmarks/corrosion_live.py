"""Controlled live Corrosion V1 benchmark preparation and scoring helpers.

This module does not make provider calls at import time. A live run is deliberately one
paper at a time, uses benchmark provider mode, disables Serper/search enrichment, and
writes only to the git-ignored ``output/`` workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from synthex_platform.benchmarks.corrosion import (
    CorrosionBenchmarkScore,
    CorrosionExpectedObservation,
    score_corrosion_archive,
)
from synthex_platform.extraction import SynthexExtractionPipeline
from synthex_platform.visual.sidecar_store import VisualSidecarStore


HOLDOUT_CASE_ID = "CORR-HOLDOUT-I"


@dataclass(frozen=True)
class CorrosionLiveCase:
    case_id: str
    role: str
    filename: str
    title: str
    doi: str
    pdf_path: Path
    gold_path: Path | None
    expected_domain: str


def _benchmark_root(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / "benchmark" / "corrosion_v1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_live_case(case_id: str, repo_root: str | Path) -> CorrosionLiveCase:
    """Resolve one locked benchmark case without invoking external services."""
    case_id = case_id.strip().upper()
    if case_id == HOLDOUT_CASE_ID:
        raise ValueError(
            "CORR-HOLDOUT-I is reserved as the localized-corrosion holdout and is not available for tuning/live Stage 3 runs."
        )

    root = _benchmark_root(repo_root)
    manifest = _read_json(root / "corpus_manifest.json")
    entry = next((item for item in manifest.get("entries", []) if item.get("id") == case_id), None)
    if entry is None:
        known = ", ".join(item.get("id", "") for item in manifest.get("entries", []) if item.get("id") != HOLDOUT_CASE_ID)
        raise ValueError(f"Unknown Corrosion V1 case {case_id!r}. Available cases: {known}")

    pdf_path = root / "corpus pdfs" / entry["filename"]
    if not pdf_path.exists():
        raise FileNotFoundError(f"Benchmark PDF is missing: {pdf_path}")

    gold_path = root / "gold" / f"{case_id}.json"
    if not gold_path.exists():
        gold_path = None

    expected_domain = "not_corrosion" if entry.get("role") == "non_corrosion_negative_control" else "corrosion"
    return CorrosionLiveCase(
        case_id=case_id,
        role=str(entry.get("role") or ""),
        filename=str(entry["filename"]),
        title=str(entry.get("expected_title") or ""),
        doi=str(entry.get("expected_doi") or ""),
        pdf_path=pdf_path,
        gold_path=gold_path,
        expected_domain=expected_domain,
    )


def expectations_from_gold(gold: dict[str, Any]) -> tuple[CorrosionExpectedObservation, ...]:
    """Translate only explicitly scored numeric gold observations into scorer assertions.

    No unit conversion, reference-electrode conversion, or value inference is performed.
    """
    expected: list[CorrosionExpectedObservation] = []
    for item in gold.get("scored_numeric_observations", []):
        expected.append(CorrosionExpectedObservation(
            metric=str(item["metric"]),
            value=float(item["value"]),
            unit=str(item["unit"]),
            experiment_type=item.get("experiment_type"),
            material_contains=item.get("material_contains"),
            reference_electrode=item.get("reference_electrode"),
            tolerance_abs=float(item.get("tolerance_abs", 1e-9)),
            required=bool(item.get("required", True)),
        ))
    return tuple(expected)


def build_live_pipeline(output_directory: str | Path) -> SynthexExtractionPipeline:
    """Build the quota-conscious live benchmark pipeline without network search or OCR."""
    return SynthexExtractionPipeline(
        search_assisted=False,
        find_supplementary=False,
        enable_ocr=False,
        provider_mode="benchmark",
        visual_sidecar_store=VisualSidecarStore(output_directory),
    )


def _score_payload(score: CorrosionBenchmarkScore | None) -> dict[str, Any] | None:
    return score.as_dict() if score is not None else None


def run_live_corrosion_case(case_id: str, repo_root: str | Path) -> dict[str, Any]:
    """Run exactly one live benchmark paper and persist its archive/report under ``output/``."""
    repo_root = Path(repo_root).resolve()
    load_dotenv(repo_root / ".env", override=True)
    case = load_live_case(case_id, repo_root)

    output_dir = repo_root / "output" / "corrosion_v1" / "live" / case.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = build_live_pipeline(output_dir)

    bundle = pipeline.build_source_bundle(case.pdf_path, source_filename=case.filename)
    route, archive = pipeline.extract_source_bundle(bundle, domain="auto")

    archive_path = output_dir / "archive.json"
    archive_path.write_text(archive.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

    route_ok = route.domain != "corrosion" if case.expected_domain == "not_corrosion" else route.domain == case.expected_domain
    expectations: tuple[CorrosionExpectedObservation, ...] = ()
    score: CorrosionBenchmarkScore | None = None
    if case.gold_path is not None:
        gold = _read_json(case.gold_path)
        expectations = expectations_from_gold(gold)
        if route.domain == "corrosion" and expectations:
            score = score_corrosion_archive(archive, expectations)

    report: dict[str, Any] = {
        "case_id": case.case_id,
        "role": case.role,
        "paper": {
            "filename": case.filename,
            "title": case.title,
            "doi": case.doi,
        },
        "run_policy": {
            "provider_mode": "benchmark",
            "search_assisted": False,
            "ocr_enabled": False,
            "one_paper_per_run": True,
            "production_archive_mutated": False,
        },
        "routing": {
            "expected_domain": case.expected_domain,
            "resolved_domain": route.domain,
            "confidence": route.confidence,
            "method": route.method,
            "route_ok": route_ok,
        },
        "gold_assertions": len(expectations),
        "score": _score_payload(score),
        "extraction_diagnostics": pipeline.last_extraction_diagnostics,
        "provider_audit": pipeline.last_provider_audit,
        "archive_path": str(archive_path.relative_to(repo_root)),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    report["report_path"] = str(report_path.relative_to(repo_root))
    return report
