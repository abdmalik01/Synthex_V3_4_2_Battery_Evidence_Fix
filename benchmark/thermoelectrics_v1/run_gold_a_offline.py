"""Run deterministic TE-GOLD-A recovery and scoring."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.recover_gold_a import CASE_DIR, recover_gold_a
from benchmark.thermoelectrics_v1.score_gold_a import score_gold_a


def main() -> int:
    gold = json.loads((CASE_DIR / "gold_a.json").read_text(encoding="utf-8"))
    archive, _ = recover_gold_a()
    report = score_gold_a(archive, gold)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
