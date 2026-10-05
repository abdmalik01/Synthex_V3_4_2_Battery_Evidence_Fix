"""One controlled persistence-first PV-SPEC-B Gemini benchmark."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.photovoltaics_v1.case_common import CASE_DIR, assert_locked, read_json
from benchmark.photovoltaics_v1.raw_scoring_spec_b import score_raw_spec_b
from benchmark.photovoltaics_v1.recover_spec_b import recover_spec_b
from benchmark.photovoltaics_v1.score_additional_cases import score_spec_b
from synthex_platform.benchmarks.provider_artifacts import ProviderArtifactRecorder, create_live_run_root
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor, StructuredExtractionValidationError
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


OUT = ROOT / "output" / "photovoltaics_v1" / "live" / "PV-SPEC-B"


def _locked_case():
    lock = read_json("spec_b_source_lock.json")
    article = CASE_DIR / lock["article_file"]
    source_data = CASE_DIR / lock["source_data_file"]
    gold_path = CASE_DIR / lock["gold_file"]
    assert_locked(article, lock["article_sha256"], "PV-SPEC-B article")
    assert_locked(source_data, lock["source_data_sha256"], "PV-SPEC-B source data")
    assert_locked(gold_path, lock["gold_sha256"], "PV-SPEC-B gold")
    return article, read_json(lock["gold_file"]), lock


def _source_data_text(recovered: list[dict]) -> str:
    by_label = {item["label"]: {point["wavelength_nm"]: point["eqe_percent"] for point in item["points"]} for item in recovered}
    wavelengths = sorted({wavelength for values in by_label.values() for wavelength in values})
    lines = [
        "OFFICIAL SOURCE DATA WORKBOOK: Fig. 3b",
        "Wavelength (nm)\tPM6:BTP-eC9 EQE (%)\tPM6:o-BTP-eC9 EQE (%)\tTernary EQE (%)",
    ]
    for wavelength in wavelengths:
        values = [by_label[label].get(wavelength, "") for label in ("PM6:BTP-eC9", "PM6:o-BTP-eC9", "Ternary")]
        lines.append("\t".join([str(wavelength), *(str(value) for value in values)]))
    return "\n".join(lines)


def _persisted_raw_score(attempt_root: Path, recovered: list[dict]) -> dict | None:
    parsed = attempt_root / "parsed_response.json"
    if not parsed.exists():
        return None
    payload = json.loads(parsed.read_text(encoding="utf-8"))
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    return score_raw_spec_b(payload, recovered) if isinstance(payload, dict) else None


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    article, gold, lock = _locked_case()
    deterministic_archive, recovered = recover_spec_b()
    deterministic_score = score_spec_b(deterministic_archive, gold)
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    bundle = build_source_bundle(article, enable_ocr=False, include_figures=False)
    text = bundle.page_marked_text() + "\n\n" + _source_data_text(recovered)
    route = DomainRouter().route_text(text)
    if route.domain != "photovoltaics":
        raise ValueError(f"Locked PV-SPEC-B routed to {route.domain!r}")
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
            return {
                "provider_audit": extractor.last_provider_audit,
                "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
                "validation_failure": error.validation_errors,
                "raw_score": _persisted_raw_score(attempt_root, recovered),
                "canonical_archive": None,
                "canonical_score": None,
                "attempt_root": str(attempt_root),
            }
        (attempt_root / "canonical_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        return {
            "provider_audit": extractor.last_provider_audit,
            "extraction_diagnostics": {"schema_repair_calls": int(bool(extractor.last_repaired_output))},
            "validation_failure": None,
            "raw_score": _persisted_raw_score(attempt_root, recovered),
            "canonical_archive": archive,
            "canonical_score": score_spec_b(archive, gold),
            "attempt_root": str(attempt_root),
        }

    result, ledger = run_with_transient_retries(run_once, model=model, ledger_path=run_root / "provider_retry_ledger.json")
    if result is None:
        for attempt_root in sorted(run_root.glob("attempt-*")):
            raw_score = _persisted_raw_score(attempt_root, recovered)
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
    (run_root / "deterministic_archive.json").write_text(deterministic_archive.model_dump_json(indent=2), encoding="utf-8")
    (run_root / "deterministic_series.json").write_text(json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8")
    status = ledger["status"] if result is None else ("LIVE_PAYLOAD_SCHEMA_INVALID" if result["validation_failure"] else "LIVE_SCORED")
    report = {
        "case_id": "PV-SPEC-B",
        "status": status,
        "requested_model": model,
        "actual_model": result["provider_audit"].get("actual_model") if result else None,
        "provider_attempts": ledger["attempts"],
        "credential_path": "primary",
        "fallback": False,
        "article_sha256": lock["article_sha256"],
        "source_data_sha256": lock["source_data_sha256"],
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
        "raw_scores": report["raw_provider_scientific_score"]["scores"] if report["raw_provider_scientific_score"] else None,
        "canonical_admitted": report["canonical_admission"]["admitted"],
        "deterministic_matches": deterministic_score["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
