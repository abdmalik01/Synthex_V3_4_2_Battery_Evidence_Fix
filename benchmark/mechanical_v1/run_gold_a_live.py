"""One controlled MECH-GOLD-A live extraction, with offline recovery scored separately."""

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

from benchmark.mechanical_v1.recover_table4 import recover_table4
from benchmark.mechanical_v1.score_gold_a import score_archive
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


CASE = ROOT / "benchmark/mechanical_v1"
OUT = Path(os.getenv("MECH_GOLD_A_OUTPUT_DIR", str(ROOT / "output/mechanical_v1/live/MECH-GOLD-A")))


def load_locked_case():
    lock = json.loads((CASE / "source_lock.json").read_text(encoding="utf-8"))
    source = CASE / lock["source_file"]
    gold_path = CASE / lock["gold_file"]
    if sha256(source.read_bytes()).hexdigest() != lock["source_sha256"]:
        raise ValueError("MECH-GOLD-A source PDF has changed")
    if sha256(gold_path.read_bytes()).hexdigest() != lock["gold_sha256"]:
        raise ValueError("MECH-GOLD-A frozen gold has changed")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if len(gold["assertions"]) != lock["assertions"]:
        raise ValueError("MECH-GOLD-A assertion count differs from lock")
    return source, gold_path, gold, lock


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    source, gold_path, gold, lock = load_locked_case()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text()
    route = DomainRouter().route_text(text)
    if route.domain != "mechanical":
        raise ValueError(f"Locked MECH-GOLD-A routed to {route.domain!r}")
    OUT.mkdir(parents=True, exist_ok=True)

    def run_once():
        extractor = DomainGeminiExtractor(model=model, provider_mode="benchmark")
        archive = extractor.extract_text(text, "mechanical", source_bundle=bundle)
        for phase, response in {
            "raw": extractor.last_raw_output,
            "repaired": extractor.last_repaired_output,
        }.items():
            if response:
                (OUT / f"provider_{phase}_response.json").write_text(response, encoding="utf-8")
        (OUT / "raw_provider_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        raw_score = score_archive(archive, gold)
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "raw_score": raw_score,
            "raw_archive": archive,
        }

    result, ledger = run_with_transient_retries(
        run_once, model=model, ledger_path=OUT / "provider_retry_ledger.json",
    )
    if result is None:
        report = {
            "case_id": "MECH-GOLD-A", "status": ledger["status"],
            "model": model, "attempts": ledger["attempts"],
            "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
            "raw_provider_score": None, "post_recovery_score": None,
        }
    else:
        recovered_archive, recovered = recover_table4(source, gold_path)
        (OUT / "post_recovery_archive.json").write_text(
            recovered_archive.model_dump_json(indent=2), encoding="utf-8",
        )
        (OUT / "recovered_rows.json").write_text(
            json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        post_score = score_archive(recovered_archive, gold)
        report = {
            "case_id": "MECH-GOLD-A", "status": "LIVE_SCORED",
            "requested_model": model,
            "actual_model": result["provider_audit"].get("actual_model"),
            "provider_attempts": ledger["attempts"],
            "fallback": result["provider_audit"].get("fallback_occurred", False),
            "route": route.domain, "route_confidence": route.confidence,
            "paper_types": route.paper_types,
            "schema_repair_calls": result["extraction_diagnostics"]["schema_repair_calls"],
            "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
            "raw_provider_score": result["raw_score"],
            "post_recovery_score": post_score,
            "raw_experiments": len(result["raw_archive"].experiments),
            "raw_calculations": len(result["raw_archive"].calculations),
            "raw_quarantine": len(result["raw_archive"].domain_payloads[0].values["admissibility"]["quarantined_objects"]),
            "post_recovery_experiments": len(recovered_archive.experiments),
            "post_recovery_calculations": len(recovered_archive.calculations),
        }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "status": report["status"], "model": model,
        "attempts": len(ledger["attempts"]),
        "raw_matches": result["raw_score"]["passed"] if result else None,
        "post_matches": report["post_recovery_score"]["passed"] if result else None,
        "report": str(OUT / "report.json"),
    }
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
