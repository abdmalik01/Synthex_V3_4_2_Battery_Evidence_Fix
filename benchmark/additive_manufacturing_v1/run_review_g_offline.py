from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_review_g import recover_review_g
from benchmark.additive_manufacturing_v1.score_review_g import score_review_g


def main() -> int:
    _, gold, lock = load_locked("review_g_source_lock.json")
    archive, guarded, route = recover_review_g()
    score = score_review_g(archive, guarded, route, gold)
    out = ROOT / "output/additive_manufacturing_v1/offline/AM-REVIEW-G"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {
        "case_id": gold["case_id"], "status": "PASS_OFFLINE", "provider_invoked": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"], "score": score,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": score["passed"], "total": score["total"], "noncanonical": score["noncanonical_candidate_count"]}))
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
