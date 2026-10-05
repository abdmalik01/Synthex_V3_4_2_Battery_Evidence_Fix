"""Score frozen Creep provider JSON after its strict schema rejection; no provider call."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.score_creep_b_raw import score_raw_creep_payload


def main() -> int:
    _, gold, lock = load_locked_case("MECH-CREEP-B")
    out = ROOT / "output/mechanical_v1/live/MECH-CREEP-B/first_20260922"
    raw_path = out / "provider_raw_response.json"
    repaired_path = out / "provider_repaired_response.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    ledger = json.loads((out / "provider_retry_ledger.json").read_text(encoding="utf-8"))
    offline = json.loads((ROOT / "output/mechanical_v1/offline/MECH-CREEP-B/report.json").read_text(encoding="utf-8"))
    score = score_raw_creep_payload(raw, gold)
    provider_attempts = [
        {**attempt, "status": "structured_validation_failure",
         "payload_returned": True, "schema_repair_count": 1}
        for attempt in ledger["attempts"]
    ]
    report = {
        "case_id": "MECH-CREEP-B", "status": "LIVE_PAYLOAD_SCHEMA_INVALID",
        "requested_model": "gemini-3.5-flash", "actual_model": "gemini-3.5-flash",
        "provider_attempts": provider_attempts, "payload_returned": True,
        "schema_repair_count": int(repaired_path.exists()), "canonical_archive_admitted": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "raw_payload_sha256": sha256(raw_path.read_bytes()).hexdigest(),
        "repaired_payload_sha256": sha256(repaired_path.read_bytes()).hexdigest(),
        "raw_provider_score": score,
        "deterministic_recovery_score": offline["score"],
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "raw_matches": score["passed"],
        "raw_value_accuracy": score["value_accuracy"],
        "offline_matches": offline["score"]["passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
