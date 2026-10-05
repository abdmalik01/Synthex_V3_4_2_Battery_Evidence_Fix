from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_compute_f import recover_compute_f
from benchmark.additive_manufacturing_v1.score_compute_f import score_compute_f


def main() -> int:
    _, gold, lock = load_locked("compute_f_source_lock.json")
    archive, rows = recover_compute_f()
    score = score_compute_f(archive, gold)
    out = ROOT / "output/additive_manufacturing_v1/offline/AM-COMPUTE-F"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {"case_id": gold["case_id"], "status": "OFFLINE_DETERMINISTIC_RECOVERY", "provider_invoked": False, "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"], "score": score}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "calculations": score["calculations"]}))
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
