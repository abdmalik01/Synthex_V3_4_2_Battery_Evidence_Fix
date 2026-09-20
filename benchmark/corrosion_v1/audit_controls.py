from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.console import configure_utf8_stdio  # noqa: E402
from synthex_platform.benchmarks.corrosion_controls import (  # noqa: E402
    audit_corrosion_negative_control,
    audit_corrosion_review_control,
)


def main() -> int:
    configure_utf8_stdio()
    payload = {
        "CORR-REVIEW-G": audit_corrosion_review_control(REPO_ROOT),
        "CORR-NEGATIVE-H": audit_corrosion_negative_control(REPO_ROOT),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if all(item["score"]["overall"] == 1.0 for item in payload.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
