"""Run the provider-free AM-GOLD-A deterministic benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.recover_gold_a import recover_gold_a
from benchmark.additive_manufacturing_v1.score_gold_a import score_gold_a


CASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    gold = json.loads((CASE_DIR / "gold_a_contract.json").read_text(encoding="utf-8"))
    lock = json.loads((CASE_DIR / "source_lock.json").read_text(encoding="utf-8"))
    archive, recovered = recover_gold_a()
    score = score_gold_a(archive, gold)
    out = ROOT / "output" / "additive_manufacturing_v1" / "offline" / "AM-GOLD-A"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_rows.json").write_text(
        json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report = {
        "case_id": "AM-GOLD-A", "status": "OFFLINE_DETERMINISTIC_RECOVERY",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "score": score,
        "readiness": "locked_offline_validated_before_any_live_provider_run",
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "passed": score["passed"], "total": score["total"],
        "provider_invoked": False, "scientific_safety": score["scientific_safety"],
    }))
    return 0 if score["passed"] == score["total"] and all(
        value == 0 if key == "quarantine_count" else value
        for key, value in score["scientific_safety"].items()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
