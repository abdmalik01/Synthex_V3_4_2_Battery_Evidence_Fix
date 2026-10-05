"""Close MECH-FRACTURE-E from its frozen raw payload without another provider call."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.score_fracture_e_raw import score_raw_fracture_payload


OUT = ROOT / "output/mechanical_v1/live/MECH-FRACTURE-E/first_20260922"


def main() -> int:
    _, gold, lock = load_locked_case("MECH-FRACTURE-E")
    raw_path = OUT / "provider_raw_response.json"
    if not raw_path.exists():
        raise FileNotFoundError("Frozen Fracture provider payload is missing")
    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_score = score_raw_fracture_payload(raw_payload, gold)
    offline = json.loads(
        (ROOT / "output/mechanical_v1/offline/MECH-FRACTURE-E/report.json").read_text(encoding="utf-8")
    )
    attempt_audit = {
        "case": "MECH-FRACTURE-E", "attempt": 1, "model": "gemini-3.5-flash",
        "provider_status": "primary_payload_returned_schema_invalid_repair_quota_exhausted",
        "payload_returned": True, "credential_path": "primary", "fallback": False,
        "schema_repair_count": 1, "schema_repair_completed": False,
        "retry_performed": False,
        "retry_reason": "not retried: primary scientific payload existed and quota failure was not a quality retry",
    }
    (OUT / "provider_attempt_audit.json").write_text(
        json.dumps(attempt_audit, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    report = {
        "case_id": "MECH-FRACTURE-E",
        "status": "LIVE_PAYLOAD_SCHEMA_INVALID_REPAIR_QUOTA",
        "requested_model": "gemini-3.5-flash", "actual_model": "gemini-3.5-flash",
        "provider_attempts": [attempt_audit], "credential_path": "primary", "fallback": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "route": "mechanical", "paper_types": ["fracture_toughness"],
        "raw_provider_score": raw_score, "canonical_provider_score": None,
        "deterministic_recovery_score": offline["score"],
        "provider_archive_admitted": False, "provider_experiments": None,
        "provider_calculations": None, "provider_outputs": None,
        "raw_payload_counts": {
            "materials": len(raw_payload.get("materials", [])),
            "experiments": len(raw_payload.get("experiments", [])),
            "top_level_measurements": len(raw_payload.get("measurements", [])),
            "calculations": len(raw_payload.get("calculations", [])),
        },
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "raw_matches": raw_score["passed"],
        "raw_value_unit_accuracy": raw_score["value_unit_accuracy"],
        "deterministic_matches": offline["score"]["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
