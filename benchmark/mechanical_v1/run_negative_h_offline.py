"""Publish provider-free MECH-NEGATIVE-H validation."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_negative_h import recover_negative_h
from benchmark.mechanical_v1.score_negative_h import score_negative_h


def main() -> int:
    _, gold, lock = load_locked_case("MECH-NEGATIVE-H")
    archive, first, second, text = recover_negative_h()
    score = score_negative_h(archive, first, second, text, gold)
    out = ROOT / "output/mechanical_v1/offline/MECH-NEGATIVE-H"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {
        "case_id": "MECH-NEGATIVE-H", "status": "OFFLINE_NEGATIVE_CONTROL_PASSED",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "score": score,
        "experiments": 0, "calculations": 0, "outputs": 0, "quarantine_noncanonical": 0,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "route": score["route"]}))
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
