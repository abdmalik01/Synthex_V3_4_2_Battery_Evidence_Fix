"""Replay append-only membrane normalization from immutable raw artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.membranes_v1.provider_normalization import (
    NORMALIZER_VERSION,
    classify_provider_shape,
    normalize_provider_payload,
)
from benchmark.membranes_v1.raw_scoring import score_raw_case
from benchmark.membranes_v1.recover_cases import CASE_DIR
from synthex_platform.extraction.assembler import assemble_archive


LOCKS = {"MEM-GOLD-A": "source_lock.json", "MEM-SEP-B": "source_lock_sep_b.json"}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite append-only normalization artifact: {path}")
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replay(run_root: Path, *, case_id: str) -> dict:
    attempt = next(path for path in sorted(run_root.glob("attempt-*")) if (path / "raw_response.txt").exists())
    raw_path = attempt / "raw_response.txt"
    raw_bytes = raw_path.read_bytes()
    raw_hash = sha256(raw_bytes).hexdigest()
    sidecar = _read(attempt / "raw_response_sha256.json")["sha256"]
    if raw_hash != sidecar:
        raise ValueError("Persisted raw response no longer matches its immutable checksum sidecar")
    payload = json.loads(raw_bytes.decode("utf-8"))
    lock = _read(CASE_DIR / LOCKS[case_id])
    gold = _read(CASE_DIR / lock["gold_file"])
    timestamp = datetime.now(timezone.utc).isoformat()

    document, normalization_audit = normalize_provider_payload(payload, case_id=case_id)
    try:
        validated = document.model_validate(document.model_dump(mode="json"))
    except ValidationError as error:
        validation = {"valid": False, "errors": error.errors(include_url=False)}
        archive = None
        admission = {"admitted": False, "reason": "normalized_candidate_schema_invalid"}
    else:
        validation = {"valid": True, "errors": []}
        archive = assemble_archive(validated, domain="membranes", model=NORMALIZER_VERSION)
        quarantined = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
        canonical_outputs = sum(len(experiment.outputs) for experiment in archive.experiments)
        admission = {
            "admitted": canonical_outputs > 0,
            "canonical_materials": len(archive.materials),
            "canonical_devices": len(archive.devices),
            "canonical_processes": len(archive.processes),
            "canonical_experiments": len(archive.experiments),
            "canonical_outputs": canonical_outputs,
            "quarantined_objects": len(quarantined),
            "quarantine": quarantined,
            "reason": "admitted" if canonical_outputs else "scientific_contract_rejected_unverified_or_incomplete_evidence",
        }

    scientific_score = score_raw_case(document.model_dump(mode="json"), gold)
    envelope = {
        "schema": "synthex.membrane.normalization_audit.v1",
        "case_id": case_id,
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": timestamp,
        "source_raw_artifact": str(raw_path),
        "source_raw_sha256": raw_hash,
        "source_raw_sidecar_verified": True,
        "shape_classification": classify_provider_shape(payload, case_id=case_id),
        "normalization": normalization_audit,
    }
    candidate_payload = {
        "schema": "synthex.membrane.normalized_candidate.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": timestamp,
        "source_raw_sha256": raw_hash,
        "candidate": document.model_dump(mode="json"),
    }
    validation_payload = {
        "schema": "synthex.membrane.normalized_validation.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": timestamp,
        "source_raw_sha256": raw_hash,
        **validation,
    }
    score_payload = {
        "schema": "synthex.membrane.normalized_scientific_score.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": timestamp,
        "source_raw_sha256": raw_hash,
        "score": scientific_score,
    }
    admission_payload = {
        "schema": "synthex.membrane.normalized_admission.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": timestamp,
        "source_raw_sha256": raw_hash,
        **admission,
    }
    _write_new(run_root / "normalization_audit_v1.json", envelope)
    _write_new(run_root / "normalized_candidate_v1.json", candidate_payload)
    _write_new(run_root / "normalized_validation_v1.json", validation_payload)
    _write_new(run_root / "normalized_scientific_score_v1.json", score_payload)
    _write_new(run_root / "normalized_admission_v1.json", admission_payload)
    if archive is not None:
        _write_new(run_root / "normalized_archive_v1.json", archive.model_dump(mode="json"))
    result = {
        "case_id": case_id,
        "run_root": str(run_root),
        "source_raw_sha256": raw_hash,
        "schema_valid": validation["valid"],
        "scientific_score": scientific_score,
        "admission": admission,
    }
    print(json.dumps(result, ensure_ascii=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=tuple(LOCKS))
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    replay(args.run_root.resolve(), case_id=args.case_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
