"""Controlled persistence-first AM-POST-E live benchmark."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_post_e import recover_post_e
from benchmark.additive_manufacturing_v1.score_post_e import score_post_e
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder, create_live_run_root
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor, StructuredExtractionValidationError
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


OUT = ROOT / "output/additive_manufacturing_v1/live/AM-POST-E"


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = load_locked("post_e_source_lock.json")
    deterministic_archive, rows = recover_post_e()
    deterministic_score = score_post_e(deterministic_archive, gold)
    if deterministic_score["passed"] != deterministic_score["total"]:
        raise ValueError("AM-POST-E live gate requires passing frozen offline gold")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    if DomainRouter().route_text(text).domain != "additive_manufacturing":
        raise ValueError("Locked AM-POST-E did not route to additive_manufacturing")
    run_root = create_live_run_root(OUT)
    attempt_number = 0

    def run_once():
        nonlocal attempt_number
        attempt_number += 1
        attempt_root = run_root / f"attempt-{attempt_number}"
        recorder = ProviderArtifactRecorder(attempt_root, model=model, attempt=attempt_number)
        extractor = DomainGeminiExtractor(model=model, provider_mode="benchmark", artifact_sink=recorder)
        try:
            archive = extractor.extract_text(text, "additive_manufacturing", source_bundle=bundle)
        except StructuredExtractionValidationError as error:
            return {"provider_audit": extractor.last_provider_audit, "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))}, "validation_failure": error.validation_errors, "raw_score": None, "attempt_root": str(attempt_root)}
        (attempt_root / "canonical_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        return {"provider_audit": extractor.last_provider_audit, "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))}, "validation_failure": None, "raw_score": score_post_e(archive, gold), "attempt_root": str(attempt_root)}

    result, ledger = run_with_transient_retries(run_once, model=model, ledger_path=run_root / "provider_retry_ledger.json")
    report = {
        "case_id": "AM-POST-E", "status": ledger["status"] if result is None else ("LIVE_PAYLOAD_SCHEMA_INVALID" if result["validation_failure"] else "LIVE_SCORED"),
        "requested_model": model, "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"], "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "raw_provider_score": result["raw_score"] if result else None, "raw_validation_errors": result["validation_failure"] if result else None,
        "artifact_run_root": str(run_root), "attempt_artifact_root": result["attempt_root"] if result else None, "deterministic_score": deterministic_score,
    }
    (run_root / "deterministic_archive.json").write_text(deterministic_archive.model_dump_json(indent=2), encoding="utf-8")
    (run_root / "deterministic_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for path in (run_root / "report.json", OUT / "report.json"):
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "actual_model": report["actual_model"], "attempts": len(ledger["attempts"]), "raw_matches": result["raw_score"]["passed"] if result and result["raw_score"] else None, "deterministic_matches": deterministic_score["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
