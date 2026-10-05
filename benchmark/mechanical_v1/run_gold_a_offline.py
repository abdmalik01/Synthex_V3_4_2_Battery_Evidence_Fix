"""Publish Table 4 deterministic recovery without making a provider call."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.mechanical_v1.recover_table4 import recover_table4
from benchmark.mechanical_v1.run_gold_a_live import load_locked_case
from benchmark.mechanical_v1.score_gold_a import score_archive


def main() -> int:
    source, gold_path, gold, lock = load_locked_case()
    archive, rows = recover_table4(source, gold_path)
    score = score_archive(archive, gold)
    out = ROOT / "output/mechanical_v1/offline/MECH-GOLD-A"
    out.mkdir(parents=True, exist_ok=True)
    (out / "archive.json").write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    (out / "recovered_rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "case_id": "MECH-GOLD-A", "status": "OFFLINE_DETERMINISTIC_RECOVERY",
        "provider_invoked": False, "source_sha256": lock["source_sha256"],
        "gold_sha256": lock["gold_sha256"], "recovery_method": "locked_pdf_table4_word_geometry_v1",
        "score": score, "experiments": len(archive.experiments),
        "materials": len(archive.materials), "rows": len(rows),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "passed": score["passed"], "total": score["total"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
