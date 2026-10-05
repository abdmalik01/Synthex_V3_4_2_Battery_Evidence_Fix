"""Append an auditable scientific score to a persisted TE-GOLD-A raw payload."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.thermoelectrics_v1.raw_scoring import score_raw_gold_a
from benchmark.thermoelectrics_v1.recover_gold_a import CASE_DIR, recover_gold_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    report = json.loads((run_root / "report.json").read_text(encoding="utf-8"))
    attempt = next(path for path in sorted(run_root.glob("attempt-*")) if (path / "raw_response.txt").exists())
    raw_path = attempt / "raw_response.txt"
    raw_bytes = raw_path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    lock = json.loads((CASE_DIR / "source_lock.json").read_text(encoding="utf-8"))
    gold = json.loads((CASE_DIR / lock["gold_file"]).read_text(encoding="utf-8"))
    _, expected_series = recover_gold_a()
    score = score_raw_gold_a(payload, expected_series, gold)
    annotation = {
        "schema": "synthex.provider.posthoc_raw_scientific_score.v1",
        "provider_name": report["provider_name"], "model_id": report["model_id"],
        "run_id": report["run_id"], "case_id": report["case_id"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "raw_response_path": str(raw_path),
        "raw_response_sha256": sha256(raw_bytes).hexdigest(),
        "score": score,
        "canonical_admission": False,
        "qualifies_live_payload_gate": True,
        "reason": "Persisted real provider JSON was independently parsed and scientifically scored; canonical schema admission is not required by the TE live gate.",
    }
    output = run_root / "posthoc_scientific_score.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing score annotation: {output}")
    output.write_text(json.dumps(annotation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(annotation, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
