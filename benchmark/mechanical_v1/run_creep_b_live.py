"""One controlled live MECH-CREEP-B provider run after frozen offline validation."""

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
from benchmark.mechanical_v1.score_creep_b import score_creep_b
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


OUT = ROOT / "output/mechanical_v1/live/MECH-CREEP-B/first_20260922"


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold, lock = load_locked_case("MECH-CREEP-B")
    offline_path = ROOT / "output/mechanical_v1/offline/MECH-CREEP-B/report.json"
    offline = json.loads(offline_path.read_text(encoding="utf-8"))
    if offline["source_sha256"] != lock["source_sha256"] or offline["gold_sha256"] != lock["gold_sha256"]:
        raise ValueError("Creep offline report differs from frozen source or gold")
    if not (offline["score"]["passed"] == offline["score"]["total"] == lock["assertions"]):
        raise ValueError("Creep offline benchmark has not passed")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "mechanical" or "creep_stress_rupture" not in route.paper_types:
        raise ValueError(f"Locked Creep source routed unexpectedly: {route.domain}")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    OUT.mkdir(parents=True, exist_ok=True)

    def run_once():
        extractor = DomainGeminiExtractor(model=model, provider_mode="benchmark")
        try:
            archive = extractor.extract_text(text, "mechanical", source_bundle=bundle)
        finally:
            for phase, response in (
                ("raw", extractor.last_raw_output),
                ("repaired", extractor.last_repaired_output),
            ):
                if response:
                    (OUT / f"provider_{phase}_response.json").write_text(response, encoding="utf-8")
        (OUT / "raw_provider_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        score = score_creep_b(archive, gold)
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "raw_score": score,
            "archive": archive,
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=OUT / "provider_retry_ledger.json",
    )
    report = {
        "case_id": "MECH-CREEP-B", "status": "LIVE_SCORED" if result else ledger["status"],
        "requested_model": model,
        "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"],
        "credential_path": "primary", "fallback": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "route": route.domain, "paper_types": route.paper_types,
        "raw_provider_score": result["raw_score"] if result else None,
        "deterministic_recovery_score": offline["score"],
        "raw_experiments": len(result["archive"].experiments) if result else None,
        "raw_calculations": len(result["archive"].calculations) if result else None,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "attempts": len(ledger["attempts"]),
        "raw_matches": result["raw_score"]["passed"] if result else None,
        "offline_matches": offline["score"]["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
