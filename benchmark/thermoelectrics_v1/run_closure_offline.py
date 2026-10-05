"""Run deterministic, provider-free reports for the four TE closure cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.recover_closure import (
    CASE_DIR, recover_compute_e, recover_mixed_h, recover_neg_g, recover_review_f,
)
from benchmark.thermoelectrics_v1.score_closure import (
    score_compute_e, score_mixed_h, score_neg_g, score_review_f,
)


def _gold(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def build_reports() -> dict:
    compute = recover_compute_e()
    review, cited_rows = recover_review_f()
    negative, first_route, second_route, source_text = recover_neg_g()
    mixed = recover_mixed_h()
    return {
        "TE-COMPUTE-E": score_compute_e(compute, _gold("gold_compute_e.json")),
        "TE-REVIEW-F": score_review_f(review, _gold("gold_review_f.json"), cited_rows),
        "TE-NEG-G": score_neg_g(negative, _gold("gold_neg_g.json"), first_route, second_route, source_text),
        "TE-MIXED-H": score_mixed_h(mixed, _gold("gold_mixed_h.json")),
    }


def main() -> int:
    reports = build_reports()
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0 if all(report["passed"] for report in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
