"""Controlled exact-model live runner for MEM-GOLD-A and MEM-SEP-B."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.membranes_v1.raw_scoring import score_raw_case
from benchmark.membranes_v1.recover_cases import CASE_DIR, recover_gold_a, recover_sep_b
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder, create_provider_run_root
from synthex_platform.benchmarks.provider_retry import run_provider_with_retries
from synthex_platform.extraction.domain_extractor import DomainProviderExtractor, StructuredExtractionValidationError
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.providers import GeminiAdapter


OUTPUT = ROOT / "output/membranes_v1/provider_runs"
CASE_CONFIG = {
    "MEM-GOLD-A": ("source_lock.json", recover_gold_a),
    "MEM-SEP-B": ("source_lock_sep_b.json", recover_sep_b),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_score(attempt_root: Path, gold: dict) -> dict | None:
    parsed = attempt_root / "parsed_response.json"
    if not parsed.exists():
        return None
    payload = _read(parsed)
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    return score_raw_case(payload, gold) if isinstance(payload, dict) else None


def run_case(case_id: str, model_id: str, *, max_attempts: int = 3) -> dict:
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("A configured Gemini credential is required for live benchmarking.")
    lock_name, recover = CASE_CONFIG[case_id]
    lock = _read(CASE_DIR / lock_name)
    gold = _read(CASE_DIR / lock["gold_file"])
    deterministic = recover()
    article = CASE_DIR / lock["article_file"]
    bundle = build_source_bundle(article, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    if DomainRouter().route_text(text).domain != "membranes":
        raise ValueError(f"Locked {case_id} no longer routes to membranes")

    run_root, run_id = create_provider_run_root(
        OUTPUT, case_id=case_id, provider_name="gemini", model_id=model_id,
    )
    adapter = GeminiAdapter(client=genai.Client(api_key=api_key), model_id=model_id, mode="benchmark")
    extractor = DomainProviderExtractor(provider_adapter=adapter)
    attempt_number = 0

    def run_once():
        nonlocal attempt_number
        attempt_number += 1
        attempt_root = run_root / f"attempt-{attempt_number}"
        recorder = ProviderArtifactRecorder(
            attempt_root, provider="gemini", model=model_id, attempt=attempt_number,
            case_id=case_id, run_id=run_id, input_mode="locked_publisher_pdf_text",
        )
        recorder("request_metadata", {
            "provider_name": "gemini", "model_id": model_id, "case_id": case_id,
            "run_id": run_id, "attempt_number": attempt_number,
            "request_timestamp": datetime.now(timezone.utc).isoformat(),
            "input_mode": "locked_publisher_pdf_text", "benchmark_mode": True,
            "fallback_used": False,
            "source_hashes": {key: value for key, value in lock.items() if key.endswith("sha256")},
        })
        extractor.artifact_sink = recorder
        try:
            archive = extractor.extract_text(text, "membranes", source_bundle=bundle)
        except StructuredExtractionValidationError as error:
            raw_score = _raw_score(attempt_root, gold)
            if raw_score is not None:
                recorder("scientific_score", raw_score)
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
                "validation_failure": error.validation_errors, "raw_score": raw_score,
                "canonical_archive": None, "canonical_score": None,
                "attempt_root": str(attempt_root),
            }
        (attempt_root / "canonical_archive.json").write_text(
            archive.model_dump_json(indent=2), encoding="utf-8",
        )
        raw_score = _raw_score(attempt_root, gold)
        if raw_score is not None:
            recorder("scientific_score", raw_score)
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "validation_failure": None, "raw_score": raw_score,
            "canonical_archive": archive,
            "canonical_score": score_raw_case(archive.model_dump(mode="json"), gold),
            "attempt_root": str(attempt_root),
        }

    result, ledger = run_provider_with_retries(
        run_once, provider="gemini", model_id=model_id, run_id=run_id,
        ledger_path=run_root / "provider_retry_ledger.json", adapter=adapter,
        max_attempts=max_attempts, raise_nontransient=False,
    )
    payload_attempt = next((item for item in ledger["attempts"] if item.get("payload_returned")), None)
    if result is None and payload_attempt:
        for attempt_root in sorted(run_root.glob("attempt-*")):
            raw_score = _raw_score(attempt_root, gold)
            if raw_score is not None:
                result = {
                    "provider_audit": adapter.audit(),
                    "validation_failure": "repair_unavailable_after_primary_payload",
                    "raw_score": raw_score, "canonical_archive": None,
                    "canonical_score": None, "attempt_root": str(attempt_root),
                }
                break

    deterministic_score = score_raw_case(deterministic.model_dump(mode="json"), gold)
    (run_root / "deterministic_archive.json").write_text(
        deterministic.model_dump_json(indent=2), encoding="utf-8",
    )
    if result is None:
        status = ledger["status"]
    elif result["validation_failure"]:
        status = "LIVE_PAYLOAD_SCHEMA_INVALID_REPAIR_FAILED"
    else:
        status = "LIVE_PAYLOAD_VALID"
    identity = adapter.get_model_identity()
    report = {
        "provider_name": "gemini", "model_id": identity.model_id,
        "configured_model_id": identity.configured_model_id,
        "provider_reported_model_id": identity.provider_reported_model_id,
        "model_version": identity.model_version, "run_id": run_id,
        "case_id": case_id, "status": status, "attempts": ledger["attempts"],
        "payload_returned": bool(payload_attempt),
        "raw_scientific_score": result["raw_score"] if result else None,
        "schema_valid": bool(result and not result["validation_failure"]),
        "repair_attempted": any(item.get("repair_count", 0) for item in ledger["attempts"]),
        "canonical_admission": {
            "admitted": bool(result and result["canonical_archive"]),
            "validation_errors": result["validation_failure"] if result else None,
            "score": result["canonical_score"] if result else None,
        },
        "deterministic_score": deterministic_score, "fallback_used": False,
        "artifact_run_root": str(run_root),
        "attempt_artifact_root": result["attempt_root"] if result else None,
        "source_hashes": {key: value for key, value in lock.items() if key.endswith("sha256")},
        "mem_live_gate_qualifying": bool(result and result["raw_score"] is not None),
    }
    (run_root / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=tuple(CASE_CONFIG))
    parser.add_argument("--model", required=True, help="Exact ID returned by Gemini models.list")
    parser.add_argument("--max-attempts", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    run_case(args.case_id, args.model, max_attempts=args.max_attempts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
