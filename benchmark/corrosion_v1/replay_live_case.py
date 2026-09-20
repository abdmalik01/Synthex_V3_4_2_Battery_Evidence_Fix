from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.console import configure_utf8_stdio  # noqa: E402
from synthex_platform.benchmarks.corrosion_live import replay_saved_live_corrosion_case  # noqa: E402


def _percent(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Replay one saved Corrosion V1 provider document with no provider calls or artifact writes."
    )
    parser.add_argument("case_id")
    args = parser.parse_args()
    try:
        result = replay_saved_live_corrosion_case(args.case_id, REPO_ROOT)
    except Exception as exc:
        print(f"OFFLINE REPLAY FAILED · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    raw = result.get("raw_provider_score") or {}
    post = result["post_recovery_score"]
    print(f"Synthex Corrosion V1 saved-payload replay · {result['case_id']}")
    print("Provider calls: 0 · historical artifacts mutated: no")
    print(
        "Raw provider: "
        f"{raw.get('matched_required', 0)}/{raw.get('total_required', 0)} · "
        f"overall {_percent(float(raw.get('overall', 0.0)))}"
    )
    print(
        "Post-recovery: "
        f"{post['matched_required']}/{post['total_required']} · "
        f"quarantine {post['quarantine_matches']}/{post['quarantine_total']} · "
        f"overall {_percent(post['overall'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
