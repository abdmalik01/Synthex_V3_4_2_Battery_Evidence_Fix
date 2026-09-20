from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.console import configure_utf8_stdio  # noqa: E402
from synthex_platform.benchmarks.corrosion_closure import (  # noqa: E402
    build_corrosion_v1_closure_summary,
)


def main() -> int:
    configure_utf8_stdio()
    summary = build_corrosion_v1_closure_summary(REPO_ROOT)
    destination = REPO_ROOT / "output" / "corrosion_v1" / "closure" / "summary.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Closure report: {destination.relative_to(REPO_ROOT)}")
    return 0 if summary["all_cases_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
