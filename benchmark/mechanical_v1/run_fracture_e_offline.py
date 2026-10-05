"""Publish the locked provider-free MECH-FRACTURE-E benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_fracture_e import recover_fracture_e
from benchmark.mechanical_v1.score_fracture_e import score_fracture_e


def main() -> int:
    _, gold, lock = load_locked_case("MECH-FRACTURE-E")
    archive, recovered = recover_fracture_e()
    score = score_fracture_e(archive, gold)
    out = ROOT / "output/mechanical_v1/offline/MECH-FRACTURE-E"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_rows.json").write_text(json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "case_id": "MECH-FRACTURE-E", "status": "OFFLINE_DETERMINISTIC_RECOVERY",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "score": score,
        "experiments": len(archive.experiments), "materials": len(archive.materials),
        "readiness": "offline_only_complete_no_fracture_provider_call",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "provider_invoked": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
