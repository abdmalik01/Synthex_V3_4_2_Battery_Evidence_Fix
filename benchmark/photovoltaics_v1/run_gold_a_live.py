"""One controlled persistence-first PV-GOLD-A Gemini benchmark."""

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

from benchmark.photovoltaics_v1.raw_scoring import score_raw_gold_a
from benchmark.photovoltaics_v1.recover_gold_a import recover_gold_a
from benchmark.photovoltaics_v1.score_gold_a import score_gold_a
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder, create_live_run_root
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor, StructuredExtractionValidationError
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


CASE = Path(__file__).resolve().parent
OUT = ROOT / "output" / "photovoltaics_v1" / "live" / "PV-GOLD-A"


def _locked_case():
    lock = json.loads((CASE / "source_lock.json").read_text(encoding="utf-8"))
    source = CASE / lock["source_file"]
    gold_path = CASE / lock["gold_file"]
    if sha256(source.read_bytes()).hexdigest() != lock["source_sha256"]:
        raise ValueError("PV-GOLD-A source PDF has changed")
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError("PV-GOLD-A frozen gold has changed")
    return source, json.loads(gold_path.read_text(encoding="utf-8")), lock


def _persisted_raw_score(attempt_root: Path, gold: dict) -> dict | None:
    parsed = attempt_root / "parsed_response.json"
    if not parsed.exists():
        return None
    payload = json.loads(parsed.read_text(encoding="utf-8"))
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    return score_raw_gold_a(payload, gold) if isinstance(payload, dict) else None


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = _locked_case()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "photovoltaics":
        raise ValueError(f"Locked PV-GOLD-A routed to {route.domain!r}")
    run_root = create_live_run_root(OUT)
    attempt_number = 0

    def run_once():
        nonlocal attempt_number
        attempt_number += 1
        attempt_root = run_root / f"attempt-{attempt_number}"
        recorder = ProviderArtifactRecorder(attempt_root, model=model, attempt=attempt_number)
        extractor = DomainGeminiExtractor(model=model, provider_mode="benchmark", artifact_sink=recorder)
        try:
            archive = extractor.extract_text(text, "photovoltaics", source_bundle=bundle)
        except StructuredExtractionValidationError as error:
            raw_score = _persisted_raw_score(attempt_root, gold)
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
                "validation_failure": error.validation_errors,
                "raw_score": raw_score,
                "canonical_archive": None,
                "canonical_score": None,
                "attempt_root": str(attempt_root),
            }
        (attempt_root / "canonical_archive.json").write_text(
            archive.model_dump_json(indent=2), encoding="utf-8"
        )
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "validation_failure": None,
            "raw_score": _persisted_raw_score(attempt_root, gold),
            "canonical_archive": archive,
            "canonical_score": score_gold_a(archive, gold),
            "attempt_root": str(attempt_root),
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=run_root / "provider_retry_ledger.json"
    )
    if result is None:
        for attempt_root in sorted(run_root.glob("attempt-*")):
            raw_score = _persisted_raw_score(attempt_root, gold)
            if raw_score is not None:
                result = {
                    "provider_audit": json.loads((attempt_root / "provider_status.json").read_text(encoding="utf-8"))
                    if (attempt_root / "provider_status.json").exists() else {},
                    "validation_failure": "repair_unavailable_after_payload",
                    "raw_score": raw_score,
                    "canonical_archive": None,
                    "canonical_score": None,
                    "attempt_root": str(attempt_root),
                }
                break

    deterministic_archive, recovered = recover_gold_a()
    deterministic_score = score_gold_a(deterministic_archive, gold)
    (run_root / "deterministic_archive.json").write_text(
        deterministic_archive.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_root / "deterministic_rows.json").write_text(
        json.dumps(recovered, indent=2), encoding="utf-8"
    )
    status = ledger["status"] if result is None else (
        "LIVE_PAYLOAD_SCHEMA_INVALID" if result["validation_failure"] else "LIVE_SCORED"
    )
    report = {
        "case_id": "PV-GOLD-A",
        "status": status,
        "requested_model": model,
        "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"],
        "credential_path": "primary",
        "fallback": False,
        "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"],
        "raw_provider_scientific_score": result["raw_score"] if result else None,
        "canonical_admission": {
            "admitted": bool(result and result["canonical_archive"]),
            "validation_errors": result["validation_failure"] if result else None,
            "score": result["canonical_score"] if result else None,
        },
        "deterministic_score": deterministic_score,
        "artifact_run_root": str(run_root),
        "attempt_artifact_root": result["attempt_root"] if result else None,
    }
    (run_root / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "requested_model": model,
        "actual_model": report["actual_model"],
        "attempts": len(ledger["attempts"]),
        "raw_scores": report["raw_provider_scientific_score"]["scores"]
        if report["raw_provider_scientific_score"] else None,
        "canonical_admitted": report["canonical_admission"]["admitted"],
        "deterministic_matches": deterministic_score["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
