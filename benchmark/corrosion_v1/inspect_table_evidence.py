from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.corrosion_live import (  # noqa: E402
    load_live_case,
    reverify_live_quarantine_evidence,
)
from synthex_platform.extraction.source_context import build_source_bundle  # noqa: E402
from synthex_platform.visual.sidecar_store import VisualSidecarStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect stored Corrosion V1 quarantine evidence and native table extraction "
            "without Gemini, Serper, or OCR calls."
        )
    )
    parser.add_argument("case_id", nargs="?", default="CORR-COAT-B")
    return parser


def _one_line(value: object, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main() -> int:
    args = _parser().parse_args()
    case_id = args.case_id.upper()
    print(f"Synthex Corrosion V1 table-evidence inspection · {case_id}")
    print("No provider calls will be made.")

    try:
        case = load_live_case(case_id, REPO_ROOT)
        output_dir = REPO_ROOT / "output" / "corrosion_v1" / "live" / case.case_id
        reverify = reverify_live_quarantine_evidence(case_id, REPO_ROOT)
        bundle = build_source_bundle(
            case.pdf_path,
            source_filename=case.filename,
            enable_ocr=False,
            include_figures=False,
            sidecar_store=VisualSidecarStore(output_dir),
        )
    except Exception as exc:
        print(f"INSPECTION FAILED · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "Evidence: "
        f"stored verified={reverify['verified_before']}/{reverify['evidence_count']} · "
        f"verify now={reverify['verifies_now']}/{reverify['evidence_count']}"
    )
    for index, item in enumerate(reverify["items"], start=1):
        print(
            f"  E{index}: page={item.get('page')} · table_id={item.get('table_id') or '-'} · "
            f"source={item.get('source_type')} · origin={item.get('original_source_type')} · "
            f"verifies_now={item.get('verifies_now')}"
        )
        print(f"      snippet: {_one_line(item.get('snippet'))}")

    print(f"Tables detected: {len(bundle.tables)}")
    for table in bundle.tables:
        grid = table.raw_representation.get("grid", []) if isinstance(table.raw_representation, dict) else []
        print(
            f"  {table.table_id}: page={table.page} · number={table.table_number or '-'} · "
            f"caption={_one_line(table.caption or '-', 160)}"
        )
        if table.headers:
            print(f"      headers: {_one_line(table.headers, 300)}")
        elif grid:
            print(f"      first-row/header candidate: {_one_line(grid[0], 300)}")
        else:
            print("      headers: <none>")
        for row_index, row in enumerate(grid[:8]):
            print(f"      r{row_index}: {_one_line(row, 360)}")
        if len(grid) > 8:
            print(f"      ... {len(grid) - 8} more rows")

    print("TABLE-EVIDENCE INSPECTION COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
