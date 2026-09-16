from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.corrosion_live import run_live_corrosion_case  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one controlled Corrosion V1 live benchmark paper. "
            "Serper and OCR are disabled; outputs are written under output/corrosion_v1/live/."
        )
    )
    parser.add_argument(
        "case_id",
        nargs="?",
        default="CORR-GOLD-A",
        help="Benchmark case ID. Start with CORR-GOLD-A. CORR-HOLDOUT-I is intentionally blocked.",
    )
    return parser


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100.0 * value:.1f}%"


def main() -> int:
    args = _parser().parse_args()
    print(f"Synthex Corrosion V1 live benchmark · {args.case_id.upper()}")
    print("Policy: one paper · benchmark provider mode · Serper off · OCR off · no production archive mutation")
    print("Running live extraction...")

    try:
        report = run_live_corrosion_case(args.case_id, REPO_ROOT)
    except Exception as exc:
        print(f"LIVE RUN FAILED · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    routing = report["routing"]
    print(f"Route: {routing['resolved_domain']} · expected: {routing['expected_domain']} · route_ok={routing['route_ok']}")
    print(f"Gold numeric assertions: {report['gold_assertions']}")

    score = report.get("score")
    if score:
        print(
            "Score: "
            f"matched {score['matched_required']}/{score['total_required']} · "
            f"recall {_percent(score['recall'])} · "
            f"value {_percent(score['value_accuracy'])} · "
            f"association {_percent(score['association_accuracy'])} · "
            f"source tracking {_percent(score['source_tracking_coverage'])} · "
            f"overall {_percent(score['overall'])}"
        )
        if score.get("missed"):
            print("Misses:")
            for miss in score["missed"]:
                expected = miss["expected"]
                print(
                    f"  - {expected['metric']} = {expected['value']} {expected['unit']} · "
                    f"property candidates={miss['property_candidates']} · "
                    f"unit candidates={miss['unit_candidates']} · "
                    f"value candidates={miss['value_candidates']}"
                )
    else:
        print("Numeric corrosion score: n/a for this resolved route/case.")

    diagnostics = report.get("extraction_diagnostics") or {}
    if diagnostics:
        print(
            "Provider calls: "
            f"primary={diagnostics.get('primary_calls', 1)} · "
            f"schema repair={diagnostics.get('schema_repair_calls', diagnostics.get('repair_calls', 0))}"
        )

    if report.get("verified_document_path"):
        print(f"Verified replay document: {report['verified_document_path']}")
    print(f"Archive: {report['archive_path']}")
    print(f"Report: {report['report_path']}")
    print("LIVE RUN COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
