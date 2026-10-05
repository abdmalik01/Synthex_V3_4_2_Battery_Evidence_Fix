"""Replay locked CORR-DFT-F deterministic recovery from saved provider JSON only."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthex_platform.benchmarks.corrosion import score_corrosion_archive
from synthex_platform.benchmarks.corrosion_live import (
    calculation_expectations_from_gold, load_live_case, quarantine_expectations_from_gold,
)
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_extractor import (
    parse_corrosion_document_json, recover_corrosion_document_offline,
)
from synthex_platform.extraction.source_context import build_source_bundle


def main() -> int:
    case = load_live_case("CORR-DFT-F", ROOT)
    lock = json.loads((ROOT / "benchmark/corrosion_v1/corpus_lock.json").read_text(encoding="utf-8"))
    entry = next(item for item in lock["files"] if item["id"] == case.case_id)
    source_sha = sha256(case.pdf_path.read_bytes()).hexdigest()
    if source_sha != entry["sha256"]:
        raise ValueError("CORR-DFT-F PDF differs from the corpus lock")

    live_dir = ROOT / "output/corrosion_v1/live/CORR-DFT-F"
    repaired = live_dir / "provider_repaired_response.json"
    provider_file = repaired if repaired.exists() else live_dir / "provider_raw_response.json"
    provider_text = provider_file.read_text(encoding="utf-8")
    provider_sha = sha256(provider_text.encode("utf-8")).hexdigest()
    draft = parse_corrosion_document_json(provider_text)
    bundle = build_source_bundle(
        case.pdf_path, source_filename=case.filename,
        enable_ocr=False, include_figures=False,
    )
    verified = recover_corrosion_document_offline(draft, bundle)
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)
    gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
    score = score_corrosion_archive(
        archive, calculation_expectations_from_gold(gold), quarantine_expectations_from_gold(gold),
    ).as_dict()
    original_live = json.loads((live_dir / "report.json").read_text(encoding="utf-8"))
    out = ROOT / "output/corrosion_v1/offline/CORR-DFT-F"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verified_document.json").write_text(
        verified.model_dump_json(indent=2), encoding="utf-8",
    )
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {
        "case_id": case.case_id, "status": "OFFLINE_DETERMINISTIC_REPLAY",
        "provider_invoked": False, "source_sha256": source_sha,
        "provider_input_file": provider_file.name, "provider_input_sha256": provider_sha,
        "raw_provider_score_unchanged": original_live["raw_provider_score"],
        "deterministic_recovery_score": score,
        "calculation_count": len(archive.calculations),
        "calculation_output_count": sum(len(item.outputs) for item in archive.calculations),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "raw_matches": report["raw_provider_score_unchanged"]["matched_required"],
        "recovered_matches": score["matched_required"],
        "recovered_total": score["total_required"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
