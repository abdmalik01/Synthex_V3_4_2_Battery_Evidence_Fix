"""Run the provider-free AM-DENS-B benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_dens_b import recover_dens_b
from benchmark.additive_manufacturing_v1.score_dens_b import score_dens_b


def main() -> int:
    _, gold, lock = load_locked("dens_b_source_lock.json")
    archive, rows = recover_dens_b()
    score = score_dens_b(archive, gold)
    out = ROOT / "output/additive_manufacturing_v1/offline/AM-DENS-B"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    report = {"case_id": gold["case_id"], "status": "OFFLINE_DETERMINISTIC_RECOVERY", "provider_invoked": False, "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"], "score": score}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "scientific_safety": score["scientific_safety"]}))
    return 0 if score["passed"] == score["total"] and all(value == 0 if key == "quarantine_count" else value for key, value in score["scientific_safety"].items()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
