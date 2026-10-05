"""One controlled AM-DENS-B live extraction after locked offline validation."""

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
from benchmark.additive_manufacturing_v1.recover_dens_b import recover_dens_b
from benchmark.additive_manufacturing_v1.score_dens_b import score_dens_b
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder
from synthex_platform.extraction.domain_extractor import (
    DomainGeminiExtractor,
    StructuredExtractionValidationError,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


OUT = ROOT / "output/additive_manufacturing_v1/live/AM-DENS-B"


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = load_locked("dens_b_source_lock.json")
    offline_archive, rows = recover_dens_b()
    offline_score = score_dens_b(offline_archive, gold)
    if offline_score["passed"] != offline_score["total"]:
        raise ValueError("AM-DENS-B live gate requires a passing locked offline benchmark")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "additive_manufacturing":
        raise ValueError(f"Locked AM-DENS-B routed to {route.domain!r}")
    OUT.mkdir(parents=True, exist_ok=True)

    attempt_number = 0

    def run_once():
        nonlocal attempt_number
        attempt_number += 1
        recorder = ProviderArtifactRecorder(
            OUT / "attempts" / f"attempt-{attempt_number}",
            model=model,
            attempt=attempt_number,
        )
        extractor = DomainGeminiExtractor(
            model=model, provider_mode="benchmark", artifact_sink=recorder
        )
        try:
            archive = extractor.extract_text(text, "additive_manufacturing", source_bundle=bundle)
        except StructuredExtractionValidationError as error:
            if error.raw_output:
                (OUT / "provider_raw_response.json").write_text(error.raw_output, encoding="utf-8")
            if extractor.last_repaired_output:
                (OUT / "provider_repaired_response.json").write_text(extractor.last_repaired_output, encoding="utf-8")
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
                "validation_failure": error.validation_errors,
                "raw_archive": None,
                "raw_score": None,
            }
        if extractor.last_raw_output:
            (OUT / "provider_raw_response.json").write_text(extractor.last_raw_output, encoding="utf-8")
        if extractor.last_repaired_output:
            (OUT / "provider_repaired_response.json").write_text(extractor.last_repaired_output, encoding="utf-8")
        (OUT / "raw_provider_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "validation_failure": None,
            "raw_archive": archive,
            "raw_score": score_dens_b(archive, gold),
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=OUT / "provider_retry_ledger.json"
    )
    (OUT / "deterministic_archive.json").write_text(offline_archive.model_dump_json(indent=2), encoding="utf-8")
    (OUT / "deterministic_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    report = {
        "case_id": "AM-DENS-B",
        "status": ledger["status"] if result is None else ("LIVE_PAYLOAD_SCHEMA_INVALID" if result["validation_failure"] else "LIVE_SCORED"),
        "requested_model": model,
        "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"],
        "credential_path": "primary", "fallback": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "raw_provider_score": result["raw_score"] if result else None,
        "raw_validation_errors": result["validation_failure"] if result else None,
        "deterministic_score": offline_score,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "requested_model": model, "actual_model": report["actual_model"], "attempts": len(ledger["attempts"]), "raw_matches": result["raw_score"]["passed"] if result and result["raw_score"] else None, "deterministic_matches": offline_score["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
