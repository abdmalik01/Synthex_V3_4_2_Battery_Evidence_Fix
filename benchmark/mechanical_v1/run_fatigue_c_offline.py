"""Publish provider-free fatigue appendix recovery and frozen-gold score."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_fatigue_c import recover_fatigue_c
from benchmark.mechanical_v1.score_fatigue_c import score_fatigue_c


def main() -> int:
    _, gold, lock = load_locked_case("MECH-FATIGUE-C")
    archive, recovered = recover_fatigue_c()
    score = score_fatigue_c(archive, gold)
    out = ROOT / "output/mechanical_v1/offline/MECH-FATIGUE-C"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_rows.json").write_text(json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "case_id": "MECH-FATIGUE-C", "status": "OFFLINE_DETERMINISTIC_RECOVERY",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "score": score,
        "experiments": len(archive.experiments),
        "runouts": sum(item["outcome"] == "runout" for item in recovered),
        "failures": sum(item["outcome"] == "failure" for item in recovered),
        "readiness": "locked_and_offline_validated_for_later_controlled_live_run",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "passed": score["passed"], "total": score["total"],
        "runouts": report["runouts"], "provider_invoked": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
