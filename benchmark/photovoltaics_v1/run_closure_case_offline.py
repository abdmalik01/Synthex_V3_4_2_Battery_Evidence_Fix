"""Run one of the four PV closure cases without a provider call."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.photovoltaics_v1.case_common import load_locked
from benchmark.photovoltaics_v1.recover_compute_e import recover_compute_e
from benchmark.photovoltaics_v1.recover_mixed_h import recover_mixed_h
from benchmark.photovoltaics_v1.recover_negative_g import recover_negative_g
from benchmark.photovoltaics_v1.recover_review_f import recover_review_f
from benchmark.photovoltaics_v1.score_closure_cases import (
    score_compute_e,
    score_mixed_h,
    score_negative_g,
    score_review_f,
)


CASES = {
    "PV-COMPUTE-E": ("compute_e_source_lock.json", recover_compute_e, score_compute_e),
    "PV-REVIEW-F": ("review_f_source_lock.json", recover_review_f, score_review_f),
    "PV-NEG-G": ("negative_g_source_lock.json", recover_negative_g, score_negative_g),
    "PV-MIXED-H": ("mixed_h_source_lock.json", recover_mixed_h, score_mixed_h),
}


def run_case(case_id: str) -> dict:
    lock_name, recover, scorer = CASES[case_id]
    _, gold, lock = load_locked(lock_name)
    recovered = recover()
    archive = recovered[0] if isinstance(recovered, tuple) else recovered
    if case_id == "PV-COMPUTE-E":
        score = scorer(archive, recovered[1], gold)
    elif case_id == "PV-REVIEW-F":
        score = scorer(archive, recovered[1], recovered[2], gold)
    elif case_id == "PV-NEG-G":
        score = scorer(archive, recovered[1], recovered[2], recovered[3], gold)
    else:
        score = scorer(archive, gold)
    out = ROOT / "output/photovoltaics_v1/offline" / case_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    report = {
        "case_id": case_id, "status": "PASS_OFFLINE", "provider_invoked": False,
        "source_sha256": lock["source_sha256"], "gold_sha256": lock["gold_sha256"],
        "score": score,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=CASES)
    args = parser.parse_args()
    report = run_case(args.case_id)
    score = report["score"]
    print(json.dumps({
        "case_id": args.case_id, "passed": score["passed"], "total": score["total"],
        "provider_invoked": False,
    }))
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
