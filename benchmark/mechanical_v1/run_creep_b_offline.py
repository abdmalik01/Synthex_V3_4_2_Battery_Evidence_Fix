"""Publish independently scored, provider-free MECH-CREEP-B recovery."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_creep_b import recover_creep_b
from benchmark.mechanical_v1.score_creep_b import score_creep_b


def main() -> int:
    _, gold, lock = load_locked_case("MECH-CREEP-B")
    archive, recovered, omitted = recover_creep_b()
    score = score_creep_b(archive, gold)
    out = ROOT / "output/mechanical_v1/offline/MECH-CREEP-B"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_cells.json").write_text(json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "case_id": "MECH-CREEP-B", "status": "OFFLINE_DETERMINISTIC_RECOVERY",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "score": score,
        "experiments": len(archive.experiments), "recovered_cells": len(recovered),
        "omitted_NA_rows": omitted,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "omitted_NA_rows": len(omitted)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
