"""Generate the machine-readable Thermoelectrics V1 closure audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.closure_audit import build_closure_audit


def main() -> int:
    audit = build_closure_audit()
    output = Path(__file__).with_name("closure_audit.json")
    output.write_text(json.dumps(audit, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": audit["passed"], "cases": audit["case_count"],
        "outputs": audit["totals"]["canonical_outputs"],
        "invariants": audit["invariant_summary"], "contamination": audit["contamination"],
        "output": str(output),
    }, indent=2, sort_keys=True))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
