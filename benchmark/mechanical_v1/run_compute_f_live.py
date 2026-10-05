"""First controlled live MECH-COMPUTE-F provider benchmark."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.score_compute_f import score_compute_f
from benchmark.mechanical_v1.score_compute_f_raw import score_raw_compute_payload
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor, StructuredExtractionValidationError
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


OUT = ROOT / "output/mechanical_v1/live/MECH-COMPUTE-F/first_20260922"


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = load_locked_case("MECH-COMPUTE-F")
    offline = json.loads(
        (ROOT / "output/mechanical_v1/offline/MECH-COMPUTE-F/report.json").read_text(encoding="utf-8")
    )
    if offline["source_sha256"] != lock["source_sha256"] or offline["gold_sha256"] != lock["gold_sha256"]:
        raise ValueError("Compute offline report differs from frozen source or gold")
    if not (offline["score"]["passed"] == offline["score"]["total"] == lock["assertions"]):
        raise ValueError("Compute offline benchmark has not passed")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "mechanical" or "computational_mechanics" not in route.paper_types:
        raise ValueError(f"Locked Compute source routed unexpectedly: {route.domain}, {route.paper_types}")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    OUT.mkdir(parents=True, exist_ok=True)

    def run_once():
        extractor = DomainGeminiExtractor(model=model, provider_mode="benchmark")
        archive = None
        structural_status = "valid"
        try:
            archive = extractor.extract_text(text, "mechanical", source_bundle=bundle)
        except StructuredExtractionValidationError:
            structural_status = "schema_invalid"
        except Exception:
            if not extractor.last_raw_output:
                raise
            structural_status = "schema_invalid_repair_unavailable"
        finally:
            for phase, response in (
                ("raw", extractor.last_raw_output),
                ("normalized", extractor.last_normalized_output),
                ("repaired", extractor.last_repaired_output),
            ):
                if response:
                    (OUT / f"provider_{phase}_response.json").write_text(response, encoding="utf-8")
        if not extractor.last_raw_output:
            raise RuntimeError("Provider returned no payload")
        raw_payload = json.loads(extractor.last_raw_output)
        raw_score = score_raw_compute_payload(raw_payload, gold)
        canonical_score = score_compute_f(archive, gold) if archive is not None else None
        if archive is not None:
            (OUT / "provider_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        return {
            "provider_audit": extractor.last_provider_audit, "structural_status": structural_status,
            "normalization_audit": extractor.last_normalization_audit,
            "raw_score": raw_score, "canonical_score": canonical_score, "archive": archive,
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=OUT / "provider_retry_ledger.json",
    )
    if result is None:
        status = "LIVE_QUOTA_EXHAUSTED" if any(
            item.get("status") == "quota" for item in ledger["attempts"]
        ) else ledger["status"]
    elif result["structural_status"] != "valid":
        status = "LIVE_PAYLOAD_SCHEMA_INVALID"
    else:
        status = "LIVE_PAYLOAD_NORMALIZED" if result["normalization_audit"] else "LIVE_SCORED"
    report = {
        "case_id": "MECH-COMPUTE-F", "status": status, "requested_model": model,
        "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"], "credential_path": "primary", "fallback": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "route": route.domain, "paper_types": route.paper_types,
        "raw_provider_score": result["raw_score"] if result else None,
        "canonical_provider_score": result["canonical_score"] if result else None,
        "normalization_audit": result["normalization_audit"] if result else None,
        "deterministic_recovery_score": offline["score"],
        "provider_archive_admitted": bool(result and result["archive"] is not None),
        "provider_experiments": len(result["archive"].experiments) if result and result["archive"] else None,
        "provider_calculations": len(result["archive"].calculations) if result and result["archive"] else None,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": status, "attempts": len(ledger["attempts"]),
        "raw_matches": result["raw_score"]["passed"] if result else None,
        "deterministic_matches": offline["score"]["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
