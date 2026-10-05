"""Offline structural replay of the immutable MECH-CREEP-B provider response."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.score_creep_b import score_creep_b
from benchmark.mechanical_v1.score_creep_b_raw import score_raw_creep_payload
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.domain_extractor import normalize_extracted_document_structure
from synthex_platform.extraction.draft_models import ExtractedDocument
from synthex_platform.extraction.mechanical_evidence import verify_mechanical_document_evidence
from synthex_platform.extraction.mechanical_provider_normalization import normalize_mechanical_provider_payload
from synthex_platform.extraction.source_context import build_source_bundle


def main() -> int:
    source, gold, lock = load_locked_case("MECH-CREEP-B")
    out = ROOT / "output/mechanical_v1/live/MECH-CREEP-B/first_20260922"
    raw_path = out / "provider_raw_response.json"
    raw_text = raw_path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    normalized, audit = normalize_mechanical_provider_payload(raw)
    draft = ExtractedDocument.model_validate(normalize_extracted_document_structure(normalized))
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    verified = verify_mechanical_document_evidence(draft, bundle)
    archive = assemble_archive(verified, domain="mechanical", model="gemini-3.5-flash-offline-replay")
    raw_score = score_raw_creep_payload(raw, gold)
    normalized_score = score_creep_b(archive, gold)
    offline = json.loads(
        (ROOT / "output/mechanical_v1/offline/MECH-CREEP-B/report.json").read_text(encoding="utf-8")
    )
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    report = {
        "case_id": "MECH-CREEP-B",
        "status": "OFFLINE_PROVIDER_STRUCTURE_NORMALIZED_EVIDENCE_REJECTED",
        "provider_invoked": False,
        "historical_artifacts_modified": False,
        "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"],
        "raw_payload_sha256": sha256(raw_text.encode("utf-8")).hexdigest(),
        "raw_provider_score_unchanged": raw_score,
        "normalization_audit": audit,
        "normalized_measurements": sum(len(item.outputs) for item in draft.experiments),
        "normalized_structure_valid": True,
        "normalized_canonical_archive_score": normalized_score,
        "normalized_canonical_experiments": len(archive.experiments),
        "normalized_canonical_outputs": sum(len(item.outputs) for item in archive.experiments),
        "quarantine_reasons": sorted({item["reason"] for item in quarantine}),
        "scientific_interpretation": (
            "The alternate structure is recoverable, but table IDs without page, locator, and verbatim cell text "
            "cannot supply value-specific evidence. The two numerical observations at source N/A coordinates "
            "remain provider hallucinations and are not canonically admitted."
        ),
        "deterministic_source_recovery_score": offline["score"],
    }
    (out / "provider_normalized_response.json").write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "normalized_provider_archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "normalization_replay_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "raw": f"{raw_score['passed']}/{raw_score['total']}",
        "normalized_canonical": f"{normalized_score['passed']}/{normalized_score['total']}",
        "deterministic": f"{offline['score']['passed']}/{offline['score']['total']}",
        "normalized_measurements": report["normalized_measurements"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
