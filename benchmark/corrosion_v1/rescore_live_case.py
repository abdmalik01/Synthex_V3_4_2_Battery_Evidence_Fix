from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.corrosion import score_corrosion_archive  # noqa: E402
from synthex_platform.benchmarks.corrosion_live import expectations_from_gold, load_live_case  # noqa: E402
from synthex_platform.core.archive import SynthexArchive  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-score an existing Corrosion V1 live archive completely offline. "
            "No Gemini, Serper, OCR, or extraction calls are made."
        )
    )
    parser.add_argument("case_id", help="Existing live benchmark case ID, e.g. CORR-COAT-B")
    return parser


def _percent(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def main() -> int:
    args = _parser().parse_args()
    case_id = args.case_id.strip().upper()
    print(f"Synthex Corrosion V1 offline rescore · {case_id}")
    print("No provider calls will be made.")

    try:
        case = load_live_case(case_id, REPO_ROOT)
        archive_path = REPO_ROOT / "output" / "corrosion_v1" / "live" / case.case_id / "archive.json"
        if not archive_path.exists():
            raise FileNotFoundError(f"Live archive not found: {archive_path}")
        if case.gold_path is None:
            raise FileNotFoundError(f"Gold file not found for {case.case_id}")

        archive = SynthexArchive.model_validate_json(archive_path.read_text(encoding="utf-8"))
        gold = json.loads(case.gold_path.read_text(encoding="utf-8"))
        expectations = expectations_from_gold(gold)
        score = score_corrosion_archive(archive, expectations)
    except Exception as exc:
        print(f"OFFLINE RESCORE FAILED · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "Score: "
        f"matched {score.matched_required}/{score.total_required} · "
        f"recall {_percent(score.recall)} · "
        f"value {_percent(score.value_accuracy)} · "
        f"association {_percent(score.association_accuracy)} · "
        f"source tracking {_percent(score.source_tracking_coverage)} · "
        f"overall {_percent(score.overall)}"
    )
    if score.missed:
        print("Misses:")
        for miss in score.missed:
            expected = miss["expected"]
            print(
                f"  - {expected['metric']} = {expected['value']} {expected['unit']} · "
                f"property candidates={miss['property_candidates']} · "
                f"unit candidates={miss['unit_candidates']} · "
                f"value candidates={miss['value_candidates']}"
            )

    print(f"Archive: {archive_path.relative_to(REPO_ROOT)}")
    print("OFFLINE RESCORE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
