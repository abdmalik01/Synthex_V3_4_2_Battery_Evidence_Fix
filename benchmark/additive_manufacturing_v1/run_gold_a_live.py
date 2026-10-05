"""One controlled AM-GOLD-A live extraction with deterministic recovery scored separately."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.recover_gold_a import recover_gold_a
from benchmark.additive_manufacturing_v1.score_gold_a import score_gold_a
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.benchmarks.provider_artifacts import (
    ProviderArtifactRecorder,
    create_live_run_root,
)
from synthex_platform.extraction.domain_extractor import (
    DomainGeminiExtractor,
    StructuredExtractionValidationError,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


CASE = Path(__file__).resolve().parent
OUT = ROOT / "output/additive_manufacturing_v1/live/AM-GOLD-A"


def _locked_case():
    lock = json.loads((CASE / "source_lock.json").read_text(encoding="utf-8"))
    source = CASE / lock["source_file"]
    gold_path = CASE / lock["gold_file"]
    if sha256(source.read_bytes()).hexdigest() != lock["source_sha256"]:
        raise ValueError("AM-GOLD-A source PDF has changed")
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError("AM-GOLD-A frozen gold has changed")
    return source, json.loads(gold_path.read_text(encoding="utf-8")), lock


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = _locked_case()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "additive_manufacturing":
        raise ValueError(f"Locked AM-GOLD-A routed to {route.domain!r}")
    OUT.mkdir(parents=True, exist_ok=True)
    run_root = create_live_run_root(OUT)
    attempt_number = 0

    def run_once():
        nonlocal attempt_number
        attempt_number += 1
        attempt_root = run_root / f"attempt-{attempt_number}"
        recorder = ProviderArtifactRecorder(attempt_root, model=model, attempt=attempt_number)
        extractor = DomainGeminiExtractor(
            model=model, provider_mode="benchmark", artifact_sink=recorder
        )
        try:
            archive = extractor.extract_text(
                text, "additive_manufacturing", source_bundle=bundle
            )
        except StructuredExtractionValidationError as error:
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {
                    "schema_repair_calls": int(bool(extractor.last_repaired_output))
                },
                "validation_failure": error.validation_errors,
                "raw_archive": None,
                "raw_score": None,
                "attempt_root": str(attempt_root),
            }
        (attempt_root / "canonical_archive.json").write_text(
            archive.model_dump_json(indent=2), encoding="utf-8"
        )
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {
                "schema_repair_calls": int(bool(extractor.last_repaired_output))
            },
            "validation_failure": None,
            "raw_archive": archive,
            "raw_score": score_gold_a(archive, gold),
            "attempt_root": str(attempt_root),
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=run_root / "provider_retry_ledger.json"
    )
    recovered_archive, recovered = recover_gold_a()
    deterministic_score = score_gold_a(recovered_archive, gold)
    (run_root / "deterministic_archive.json").write_text(
        recovered_archive.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_root / "deterministic_rows.json").write_text(
        json.dumps(recovered, indent=2), encoding="utf-8"
    )
    report = {
        "case_id": "AM-GOLD-A",
        "status": ledger["status"] if result is None else (
            "LIVE_PAYLOAD_SCHEMA_INVALID"
            if result["validation_failure"] else "LIVE_SCORED"
        ),
        "requested_model": model,
        "actual_model": (
            result["provider_audit"].get("actual_model") if result else None
        ),
        "provider_attempts": ledger["attempts"],
        "credential_path": "primary",
        "fallback": False,
        "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"],
        "raw_provider_score": result["raw_score"] if result else None,
        "raw_validation_errors": result["validation_failure"] if result else None,
        "artifact_run_root": str(run_root),
        "attempt_artifact_root": result["attempt_root"] if result else None,
        "raw_provider_counts": ({
            "materials": len(result["raw_archive"].materials),
            "processes": len(result["raw_archive"].processes),
            "experiments": len(result["raw_archive"].experiments),
            "calculations": len(result["raw_archive"].calculations),
            "quarantine": len(result["raw_archive"].domain_payloads[0].values[
                "admissibility"
            ]["quarantined_objects"]),
        } if result and result["raw_archive"] else None),
        "deterministic_score": deterministic_score,
    }
    (run_root / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "requested_model": model,
        "actual_model": report["actual_model"],
        "attempts": len(ledger["attempts"]),
        "raw_matches": result["raw_score"]["passed"] if result and result["raw_score"] else None,
        "deterministic_matches": deterministic_score["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
