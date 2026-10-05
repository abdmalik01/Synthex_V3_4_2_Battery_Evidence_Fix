"""Run and print deterministic reports for the three TE expansion cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.recover_expansion import CASE_DIR, recover_aniso_d, recover_derived_c, recover_series_b
from benchmark.thermoelectrics_v1.score_expansion import score_aniso_d, score_derived_c, score_series_b


def _gold(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def main() -> int:
    series_archive, _ = recover_series_b()
    derived_archive, _, validation = recover_derived_c()
    aniso_archive, _ = recover_aniso_d()
    reports = {
        "TE-SERIES-B": score_series_b(series_archive, _gold("gold_series_b.json")),
        "TE-DERIVED-C": score_derived_c(derived_archive, _gold("gold_derived_c.json"), validation),
        "TE-ANISO-D": score_aniso_d(aniso_archive, _gold("gold_aniso_d.json")),
    }
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0 if all(report["passed"] for report in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
