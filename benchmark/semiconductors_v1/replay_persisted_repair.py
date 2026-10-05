"""Append-only offline validation of an already persisted schema-repair body."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from pydantic import ValidationError

from synthex_platform.benchmarks.provider_artifacts import _io_path
from synthex_platform.extraction.domain_extractor import parse_extracted_document_json
from synthex_platform.extraction.source_context import build_source_bundle

from .source_tables import ROOT, source_lock


def replay(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    case_id = report["case_id"]
    lock = source_lock(case_id)
    attempt_number = next(item["attempt_number"] for item in report["attempts"]
                          if item.get("payload_returned"))
    attempt_root = report_path.parent / f"attempt-{attempt_number}"
    repair_path = _io_path(attempt_root / "repair_response.txt")
    if not repair_path.exists():
        raise ValueError("No persisted repair response for offline replay")
    digest = sha256(repair_path.read_bytes()).hexdigest()
    expected_digest = json.loads(_io_path(attempt_root / "repair_response_sha256.json").read_text(encoding="utf-8"))["sha256"]
    if digest != expected_digest:
        raise ValueError("Persisted repair response hash mismatch")
    bundle = build_source_bundle(ROOT / lock["article_file"], enable_ocr=False, include_figures=False)
    try:
        draft = parse_extracted_document_json(repair_path.read_text(encoding="utf-8"), source_bundle=bundle)
    except ValidationError as error:
        valid = False
        errors = error.errors(include_url=False)
        draft_counts = None
    else:
        valid = True
        errors = []
        draft_counts = {name: len(getattr(draft, name)) for name in (
            "materials", "devices", "processes", "experiments", "calculations"
        )}
    artifact = {
        "case_id": case_id, "model_id": report["model_id"], "run_id": report["run_id"],
        "source": "persisted_repair_response_offline_replay",
        "repair_response_sha256": digest,
        "repair_json_schema_valid": valid, "validation_errors": errors,
        "draft_counts": draft_counts,
        "canonical_admission": False,
        "note": "This append-only replay corrects the missing repair validation artifact from the pre-fix Windows long-path prerequisite check; it does not change provider payloads or original run reports.",
    }
    path = report_path.parent / "repair_replay.json"
    with path.open("xb") as stream:
        stream.write((json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({"artifact": str(path), "repair_json_schema_valid": valid,
                      "validation_error_count": len(errors)}, ensure_ascii=True))
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    replay(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
