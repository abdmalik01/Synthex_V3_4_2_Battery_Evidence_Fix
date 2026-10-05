"""Close the authorized Compute-F live run after its non-transient quota response."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case


OUT = ROOT / "output/mechanical_v1/live/MECH-COMPUTE-F/first_20260922"


def main() -> int:
    _, _, lock = load_locked_case("MECH-COMPUTE-F")
    ledger = json.loads((OUT / "provider_retry_ledger.json").read_text(encoding="utf-8"))
    offline = json.loads(
        (ROOT / "output/mechanical_v1/offline/MECH-COMPUTE-F/report.json").read_text(encoding="utf-8")
    )
    attempts = ledger.get("attempts", [])
    if len(attempts) != 1 or attempts[0].get("status") != "quota":
        raise ValueError("Compute-F closure expects exactly one non-transient quota attempt")
    report = {
        "case_id": "MECH-COMPUTE-F",
        "status": "LIVE_QUOTA_EXHAUSTED",
        "requested_model": ledger["model"],
        "actual_model": None,
        "provider_attempts": attempts,
        "credential_path": "primary",
        "fallback": False,
        "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"],
        "route": "mechanical",
        "paper_types": ["computational_mechanics"],
        "raw_provider_score": None,
        "canonical_provider_score": None,
        "deterministic_recovery_score": offline["score"],
        "provider_archive_admitted": False,
        "provider_experiments": None,
        "provider_calculations": None,
        "closure_note": "Daily request quota rejected the primary call before a scientific payload; no retry or model fallback was performed.",
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "attempts": 1, "deterministic_matches": offline["score"]["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
