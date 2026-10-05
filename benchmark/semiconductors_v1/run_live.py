"""Exact-model Gemini benchmark with immutable raw-before-validation artifacts.

Source egress is authorized only for SEM-GOLD-A and SEM-TRANSPORT-B. This
runner does not perform model discovery or silently change models.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from synthex_platform.benchmarks.provider_artifacts import (
    ProviderArtifactRecorder, create_provider_run_root,
)
from synthex_platform.benchmarks.provider_retry import run_provider_with_retries
from synthex_platform.extraction.domain_extractor import (
    DomainProviderExtractor, StructuredExtractionValidationError,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.providers import GeminiAdapter

from .recover_cases import recover_gold_a, recover_transport_b
from .source_tables import ROOT as CASE_DIR, source_lock


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/semiconductors_v1/provider_runs"
RECOVER = {"SEM-GOLD-A": recover_gold_a, "SEM-TRANSPORT-B": recover_transport_b}


def _write_new(path: Path, data: bytes) -> None:
    resolved = path.resolve()
    io_path = Path("\\\\?\\" + str(resolved)) if os.name == "nt" and len(str(resolved)) >= 240 else path
    io_path.parent.mkdir(parents=True, exist_ok=True)
    with io_path.open("xb") as stream:
        stream.write(data)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _discovered_model(path: Path, model_id: str) -> None:
    discovery = json.loads(path.read_text(encoding="utf-8"))
    eligible = {item["model_id"] for item in discovery["eligible_general_text_models"]}
    if model_id not in eligible:
        raise ValueError(f"Model ID not in the supplied fresh discovery artifact: {model_id}")


def run_case(case_id: str, model_id: str, discovery_path: Path, *, max_attempts: int = 3) -> dict:
    if case_id not in RECOVER:
        raise ValueError(f"Unapproved Semiconductor live case: {case_id}")
    _discovered_model(discovery_path, model_id)
    lock = source_lock(case_id)  # Checks both the PDF and the pre-existing gold hash.
    deterministic = RECOVER[case_id]()
    bundle = build_source_bundle(
        CASE_DIR / lock["article_file"], enable_ocr=False, include_figures=False,
    )
    source_text = bundle.page_marked_text()
    if DomainRouter().route_text(source_text).domain != "semiconductors":
        raise ValueError(f"Locked {case_id} no longer routes to Semiconductors")

    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("A configured Gemini credential is required for live benchmarking.")
    run_root, run_id = create_provider_run_root(
        OUTPUT, case_id=case_id, provider_name="gemini", model_id=model_id,
    )
    adapter = GeminiAdapter(client=genai.Client(api_key=api_key), model_id=model_id, mode="benchmark")
    extractor = DomainProviderExtractor(provider_adapter=adapter)
    prompt = extractor.build_prompt(source_text, "semiconductors", source_bundle=bundle)
    _write_new(run_root / "request_prompt.txt", prompt.encode("utf-8"))
    _write_new(run_root / "deterministic_archive.json", deterministic.model_dump_json(indent=2).encode("utf-8"))
    _write_new(run_root / "input_manifest.json", _json_bytes({
        "case_id": case_id, "model_id": model_id, "discovery_artifact": str(discovery_path.resolve()),
        "source_lock": lock, "source_text_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "deterministic_outputs": sum(len(item.outputs) for item in deterministic.experiments),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))
    attempt_number = 0

    def run_once() -> dict:
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
            "fallback_used": False, "article_sha256": lock["article_sha256"],
            "gold_sha256": lock["gold_sha256"],
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        })
        extractor.artifact_sink = recorder
        try:
            archive = extractor.extract_text(source_text, "semiconductors", source_bundle=bundle)
        except StructuredExtractionValidationError as error:
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
                "validation_failure": error.validation_errors,
                "canonical_archive": None, "attempt_root": str(attempt_root),
            }
        _write_new(attempt_root / "canonical_archive.json", archive.model_dump_json(indent=2).encode("utf-8"))
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "validation_failure": None,
            "canonical_archive": archive, "attempt_root": str(attempt_root),
        }

    result, ledger = run_provider_with_retries(
        run_once, provider="gemini", model_id=model_id, run_id=run_id,
        ledger_path=run_root / "provider_retry_ledger.json", adapter=adapter,
        max_attempts=max_attempts, raise_nontransient=False,
    )
    payload_attempt = next((item for item in ledger["attempts"] if item.get("payload_returned")), None)
    if result is None and payload_attempt:
        status = "LIVE_PAYLOAD_REPAIR_UNAVAILABLE"
    elif result is None:
        status = ledger["status"]
    elif result["validation_failure"]:
        status = "LIVE_PAYLOAD_SCHEMA_INVALID_REPAIR_FAILED"
    else:
        status = "LIVE_PAYLOAD_VALID"
    identity = adapter.get_model_identity()
    report = {
        "provider_name": "gemini", "case_id": case_id, "model_id": identity.model_id,
        "configured_model_id": identity.configured_model_id,
        "provider_reported_model_id": identity.provider_reported_model_id,
        "model_version": identity.model_version, "run_id": run_id, "status": status,
        "attempts": ledger["attempts"], "payload_returned": bool(payload_attempt),
        "schema_valid": bool(result and not result["validation_failure"]),
        "repair_attempted": any(item.get("repair_count", 0) for item in ledger["attempts"]),
        "canonical_admission": {
            "admitted": bool(result and result["canonical_archive"]),
            "validation_errors": result["validation_failure"] if result else None,
        },
        "scientific_score_status": "PENDING_OFFLINE_RAW_SCORING" if payload_attempt else "NO_PAYLOAD",
        "artifact_run_root": str(run_root),
        "attempt_artifact_root": result["attempt_root"] if result else None,
        "source_hashes": {"article_sha256": lock["article_sha256"], "gold_sha256": lock["gold_sha256"]},
        "fallback_used": False,
        "sem_live_gate_qualifying": False,
    }
    _write_new(run_root / "report.json", _json_bytes(report))
    print(json.dumps({
        "case_id": case_id, "model_id": model_id, "run_id": run_id, "status": status,
        "attempts": len(ledger["attempts"]), "payload_returned": bool(payload_attempt),
        "artifact_run_root": str(run_root),
    }, ensure_ascii=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=tuple(RECOVER))
    parser.add_argument("--model", required=True, help="Exact ID from --discovery")
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    run_case(args.case_id, args.model, args.discovery, max_attempts=args.max_attempts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
