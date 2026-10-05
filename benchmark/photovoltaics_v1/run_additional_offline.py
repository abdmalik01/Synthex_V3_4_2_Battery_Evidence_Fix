"""Run the provider-free PV-SPEC-B, PV-STAB-C, and PV-STACK-D cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.photovoltaics_v1.case_common import CASE_DIR, read_json
from benchmark.photovoltaics_v1.recover_spec_b import recover_spec_b
from benchmark.photovoltaics_v1.recover_stab_c import recover_stab_c
from benchmark.photovoltaics_v1.recover_stack_d import recover_stack_d
from benchmark.photovoltaics_v1.score_additional_cases import score_spec_b, score_stab_c, score_stack_d


CASES = (
    ("PV-SPEC-B", "spec_b_gold.json", "spec_b_source_lock.json", recover_spec_b, score_spec_b),
    ("PV-STAB-C", "stab_c_gold.json", "stab_c_source_lock.json", recover_stab_c, score_stab_c),
    ("PV-STACK-D", "stack_d_gold.json", "stack_d_source_lock.json", recover_stack_d, score_stack_d),
)


def main() -> int:
    summaries = []
    failed = False
    for case_id, gold_file, lock_file, recover, scorer in CASES:
        gold = read_json(gold_file)
        lock = read_json(lock_file)
        archive, recovered = recover()
        score = scorer(archive, gold)
        out = ROOT / "output" / "photovoltaics_v1" / "offline" / case_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
        (out / "recovered.json").write_text(json.dumps(recovered, indent=2, ensure_ascii=False), encoding="utf-8")
        report = {
            "case_id": case_id,
            "status": "OFFLINE_DETERMINISTIC_RECOVERY",
            "provider_invoked": False,
            "source_lock": lock,
            "score": score,
            "readiness": "locked_offline_validated_before_any_live_provider_run",
        }
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        case_failed = score["passed"] != score["total"] or not all(
            value == 0 if key == "quarantine_count" else value
            for key, value in score["scientific_safety"].items()
        )
        failed = failed or case_failed
        summaries.append({
            "case_id": case_id,
            "passed": score["passed"],
            "total": score["total"],
            "outputs": score["outputs"],
            "provider_invoked": False,
            "scientific_safety": score["scientific_safety"],
        })
    print(json.dumps(summaries, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
