"""Authorized, exact-model Biomaterials live gate with immutable raw artifacts.

Only BIO-GOLD-A and BIO-BIOACT-B may be transmitted by this runner.
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

from .offline_recovery import LOCKS, ROOT as CASE_DIR
from .prepare_live import LIVE_CASES, REPO, prepare


OUTPUT = REPO / "output/biomaterials_v1/provider_runs"
SELECTION = CASE_DIR / "candidate_selection.json"
APPROVED_MODELS = (
    "models/gemini-3.7-flash",
    "models/gemini-3.6-flash",
    "models/gemini-3.1-pro-preview",
)


def _verify_approved_selection(discovery_path: Path) -> None:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    selected = tuple(item["model_id"] for item in selection["selected_exact_models"])
    if selected != APPROVED_MODELS or selection["provider"] != "gemini":
        raise ValueError("Pinned Biomaterials Gemini selection changed")
    expected_discovery = REPO / selection["discovery_artifact"]
    if discovery_path.resolve() != expected_discovery.resolve():
        raise ValueError("Biomaterials discovery artifact differs from approved selection")
    if sha256(expected_discovery.read_bytes()).hexdigest() != selection["discovery_sha256"]:
        raise ValueError("Approved Gemini discovery hash mismatch")
    if selection["source_candidates_in_order"] != list(LIVE_CASES) or selection["gold_will_be_transmitted"]:
        raise ValueError("Approved Biomaterials source-only scope changed")
    if selection["maximum_transient_attempts_per_model"] != 3:
        raise ValueError("Approved Biomaterials attempt budget changed")


def _write_new(path: Path, data: bytes) -> None:
    resolved = path.resolve()
    io_path = Path("\\\\?\\" + str(resolved)) if os.name == "nt" and len(str(resolved)) >= 240 else path
    io_path.parent.mkdir(parents=True, exist_ok=True)
    with io_path.open("xb") as stream:
        stream.write(data)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _prior_attempt_count(model_id: str) -> int:
    """Count A/B attempt artifacts, including interrupted or incomplete runs."""
    count = 0
    for path in OUTPUT.rglob("attempt_metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("model") == model_id and metadata.get("case_id") in LIVE_CASES:
            count += 1
    return count


def run_case(case_id: str, model_id: str, discovery_path: Path, *, max_attempts: int = 3) -> dict:
    if max_attempts not in (1, 2, 3):
        raise ValueError("At most three same-model attempts are permitted")
    if case_id not in LIVE_CASES:
        raise ValueError(f"Unapproved Biomaterials live case: {case_id}")
    if model_id not in APPROVED_MODELS:
        raise ValueError(f"Unapproved exact Gemini model: {model_id}")
    prior_attempts = _prior_attempt_count(model_id)
    if prior_attempts + max_attempts > 3:
        raise ValueError(
            f"Three-attempt model-wide budget exceeded: {prior_attempts} already recorded, "
            f"{max_attempts} requested"
        )
    _verify_approved_selection(discovery_path)
    plan = prepare(discovery_path, candidates=APPROVED_MODELS)
    if model_id not in plan["candidate_exact_models"]:
        raise ValueError("Exact model absent from discovery-checked plan")
    if any(item["gold_in_prompt"] or item["gold_used"] != "hash_verification_only" for item in plan["inputs"]):
        raise ValueError("Gold data must not enter Biomaterials provider prompts")
    lock = LOCKS[case_id]
    bundle = build_source_bundle(CASE_DIR / lock["pdf"], enable_ocr=False, include_figures=False)
    source_text = bundle.page_marked_text()
    if DomainRouter().route_text(source_text).domain != "biomaterials":
        raise ValueError(f"Locked {case_id} no longer routes to Biomaterials")

    load_dotenv(REPO / ".env", override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Configured Gemini credential required")
    adapter = GeminiAdapter(client=genai.Client(api_key=api_key), model_id=model_id, mode="benchmark")
    extractor = DomainProviderExtractor(provider_adapter=adapter)
    prompt = extractor.build_prompt(source_text, "biomaterials", source_bundle=bundle)
    planned = next(item for item in plan["inputs"] if item["case_id"] == case_id)
    if sha256(source_text.encode("utf-8")).hexdigest() != planned["source_text_sha256"]:
        raise ValueError("Live source text differs from locked local preparation")
    if sha256(prompt.encode("utf-8")).hexdigest() != planned["prompt_sha256"]:
        raise ValueError("Live prompt differs from locked local preparation")
    run_root, run_id = create_provider_run_root(
        OUTPUT, case_id=case_id, provider_name="gemini", model_id=model_id,
    )
    _write_new(run_root / "request_prompt.txt", prompt.encode("utf-8"))
    _write_new(run_root / "input_manifest.json", _json_bytes({
        "case_id": case_id, "model_id": model_id,
        "discovery_artifact": str(discovery_path.resolve()),
        "candidate_selection_sha256": sha256(SELECTION.read_bytes()).hexdigest(),
        "source_lock": lock,
        "source_text_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "gold_used": "hash_verification_only",
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
            "fallback_used": False, "article_sha256": lock["pdf_sha256"],
            "gold_sha256": lock["gold_sha256"],
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        })
        extractor.artifact_sink = recorder
        try:
            archive = extractor.extract_text(source_text, "biomaterials", source_bundle=bundle)
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
            "validation_failure": None, "canonical_archive": archive,
            "attempt_root": str(attempt_root),
        }

    result, ledger = run_provider_with_retries(
        run_once, provider="gemini", model_id=model_id, run_id=run_id,
        ledger_path=run_root / "provider_retry_ledger.json", adapter=adapter,
        max_attempts=max_attempts, raise_nontransient=False,
    )
    payload_attempt = any(item.get("payload_returned") for item in ledger["attempts"])
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
        "model_version": identity.model_version, "run_id": run_id,
        "status": status, "attempts": ledger["attempts"],
        "payload_returned": payload_attempt,
        "schema_valid": (bool(result and not result["validation_failure"])
                         if payload_attempt else None),
        "repair_attempted": any(item.get("repair_count", 0) for item in ledger["attempts"]),
        "canonical_admission": {
            "admitted": (bool(result and result["canonical_archive"])
                         if payload_attempt else None),
            "validation_errors": result["validation_failure"] if result else None,
        },
        "scientific_score_status": "PENDING_OFFLINE_RAW_SCORING" if payload_attempt else "NO_PAYLOAD",
        "artifact_run_root": str(run_root),
        "attempt_artifact_root": result["attempt_root"] if result else None,
        "source_hashes": {"article_sha256": lock["pdf_sha256"], "gold_sha256": lock["gold_sha256"]},
        "fallback_used": False, "bio_live_gate_qualifying": False,
    }
    _write_new(run_root / "report.json", _json_bytes(report))
    print(json.dumps({
        "case_id": case_id, "model_id": model_id, "run_id": run_id,
        "status": status, "attempts": len(ledger["attempts"]),
        "payload_returned": payload_attempt, "artifact_run_root": str(run_root),
    }, ensure_ascii=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=LIVE_CASES)
    parser.add_argument("--model", required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    run_case(args.case_id, args.model, args.discovery, max_attempts=args.max_attempts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
