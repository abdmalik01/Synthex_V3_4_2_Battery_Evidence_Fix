from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synthex_platform.benchmarks.corrosion_live import (  # noqa: E402
    diagnose_live_output,
    reverify_live_quarantine_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect an existing Corrosion V1 live-run archive/report without calling Gemini."
    )
    parser.add_argument("case_id", nargs="?", default="CORR-GOLD-A")
    return parser


def main() -> int:
    args = _parser().parse_args()
    case_id = args.case_id.upper()
    print(f"Synthex Corrosion V1 offline diagnosis · {case_id}")
    print("No provider calls will be made.")
    try:
        diagnostic = diagnose_live_output(case_id, REPO_ROOT)
        reverify = reverify_live_quarantine_evidence(case_id, REPO_ROOT)
    except Exception as exc:
        print(f"DIAGNOSIS FAILED · {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "Archive: "
        f"domain={diagnostic['archive_domain']} · "
        f"materials={diagnostic['material_count']} · "
        f"experiments={diagnostic['experiment_count']} · "
        f"canonical metrics={diagnostic['canonical_metric_count']}"
    )

    if diagnostic["experiments"]:
        print("Canonical experiments:")
        for item in diagnostic["experiments"]:
            print(
                f"  - {item['experiment_type']} · outputs={item['output_count']} · "
                f"materials={len(item['material_ids'])}"
            )

    if diagnostic["canonical_metrics"]:
        print("Canonical metrics:")
        for item in diagnostic["canonical_metrics"]:
            print(
                f"  - {item['property']} = {item['value']} {item['unit']} · "
                f"experiment={item.get('experiment_type')} · evidence={item['verified_evidence_count']}/{item['evidence_count']} verified"
            )
    else:
        print("Canonical metrics: none")

    print(f"Quarantine entries: {diagnostic['quarantine_entry_count']}")
    if diagnostic["quarantine_reason_counts"]:
        print("Quarantine reasons:")
        for reason, count in diagnostic["quarantine_reason_counts"].items():
            print(f"  - {reason}: {count}")

    if diagnostic["quarantined_metrics"]:
        print("Quarantined metrics:")
        for item in diagnostic["quarantined_metrics"]:
            print(
                f"  - {item['property']} = {item['value']} {item['unit']} · "
                f"reason={item['reason']} · ownership={item['ownership']} · "
                f"evidence={item['verified_evidence_count']}/{item['evidence_count']} verified · path={item['path']}"
            )

    print(
        "Offline evidence re-verification with current rules: "
        f"stored verified={reverify['verified_before']}/{reverify['evidence_count']} · "
        f"verify now={reverify['verifies_now']}/{reverify['evidence_count']} · "
        f"tables detected={reverify['tables_detected']}"
    )
    changed = [item for item in reverify["items"] if item["verifies_now"] and not item["was_verified"]]
    if changed:
        print("Evidence newly verifiable without another provider call:")
        for item in changed[:20]:
            snippet = (item.get("snippet") or "").replace("\n", " ")
            if len(snippet) > 140:
                snippet = snippet[:137] + "..."
            print(
                f"  - page={item.get('verified_page')} · origin={item.get('verified_origin')} · "
                f"table={item.get('table_id') or '-'} · {snippet}"
            )
    elif reverify["evidence_count"] and reverify["verifies_now"]:
        print(
            "The currently verifiable evidence was already stored as verified; "
            "the old rejection therefore came from the separate record-level evidence gate, "
            "not from newly improved matching."
        )
    elif reverify["evidence_count"]:
        print("No previously rejected evidence becomes verifiable under the current exact-match rules.")

    extraction = diagnostic["extraction_diagnostics"]
    if extraction:
        print("Extraction diagnostics:")
        for key in sorted(extraction):
            if key == "provider":
                continue
            print(f"  - {key}: {extraction[key]}")

    print(f"Existing archive: {diagnostic['archive_path']}")
    print(f"Existing report: {diagnostic['report_path']}")
    print("OFFLINE DIAGNOSIS COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
