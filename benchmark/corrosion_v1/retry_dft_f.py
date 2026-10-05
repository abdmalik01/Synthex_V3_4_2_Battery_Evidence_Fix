"""Retry only locked CORR-DFT-F on transient provider unavailability."""

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

from synthex_platform.benchmarks.corrosion_live import load_live_case, run_live_corrosion_case
from synthex_platform.benchmarks.provider_retry import run_with_transient_retries


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    case = load_live_case("CORR-DFT-F", ROOT)
    lock = json.loads((ROOT / "benchmark/corrosion_v1/corpus_lock.json").read_text(encoding="utf-8"))
    entry = next(item for item in lock["files"] if item["id"] == case.case_id)
    if sha256(case.pdf_path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError("CORR-DFT-F locked PDF checksum mismatch")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    ledger_path = ROOT / "output/corrosion_v1/live/CORR-DFT-F/provider_retry_ledger.json"
    report, ledger = run_with_transient_retries(
        lambda: run_live_corrosion_case(case.case_id, ROOT),
        model=model, ledger_path=ledger_path,
    )
    print(json.dumps({
        "status": ledger["status"], "model": model, "attempts": len(ledger["attempts"]),
        "raw_matches": report["raw_provider_score"]["matched_required"] if report else None,
        "post_recovery_matches": report["score"]["matched_required"] if report else None,
        "ledger": str(ledger_path),
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
