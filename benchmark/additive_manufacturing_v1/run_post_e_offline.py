from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_post_e import recover_post_e
from benchmark.additive_manufacturing_v1.score_post_e import score_post_e


def main() -> int:
    _, gold, lock = load_locked("post_e_source_lock.json")
    archive, rows = recover_post_e()
    score = score_post_e(archive, gold)
    out = ROOT / "output/additive_manufacturing_v1/offline/AM-POST-E"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {"case_id": gold["case_id"], "status": "OFFLINE_DETERMINISTIC_RECOVERY", "provider_invoked": False, "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"], "score": score}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "values": score["mechanical_value_count"]}))
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
