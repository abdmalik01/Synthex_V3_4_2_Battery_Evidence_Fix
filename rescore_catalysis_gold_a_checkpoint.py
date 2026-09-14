"""Offline rescore for an already-saved Catalysis Gold A checkpoint.

No Gemini, Serper, PDF parsing, extraction, repair, or archive mutation is performed.
The script only reloads the saved validated archive and independently curated Gold A
record, then applies conservative scoring normalization from benchmark_catalysis_scoring_v2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_catalysis_scoring_v2 import score_metric_association


ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "benchmark" / "catalysis_v1" / "outputs"
GOLD_PATH = ROOT / "benchmark" / "catalysis_v1" / "gold" / "gold_a_heterogeneous_experimental.json"


def _latest_checkpoint() -> Path:
    candidates = [
        path for path in OUTPUT_ROOT.glob("gold_a_checkpoint_*")
        if path.is_dir() and (path / "cat-gold-a_result.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No saved Gold A checkpoint directory containing cat-gold-a_result.json was found.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load_document(result: dict) -> dict:
    archive = result.get("archive") or {}
    payloads = [
        item for item in archive.get("domain_payloads", [])
        if isinstance(item, dict) and item.get("domain") == "catalysis"
    ]
    if not payloads:
        raise ValueError("Saved result does not contain a validated Catalysis archive payload.")
    values = payloads[0].get("values") or {}
    document = values.get("validated_document")
    if not isinstance(document, dict):
        raise ValueError("Saved Catalysis payload does not contain validated_document.")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description="Rescore a saved Gold A checkpoint without external calls.")
    parser.add_argument(
        "checkpoint",
        nargs="?",
        type=Path,
        help="Checkpoint directory. Defaults to the most recently modified gold_a_checkpoint_* directory.",
    )
    args = parser.parse_args()

    checkpoint = (args.checkpoint or _latest_checkpoint()).resolve()
    result_path = checkpoint / "cat-gold-a_result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Missing saved Gold A result: {result_path}")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("extraction_status") != "schema_valid":
        raise ValueError(
            f"Saved checkpoint has extraction_status={result.get('extraction_status')!r}; "
            "there is no validated scientific result to rescore."
        )

    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    document = _load_document(result)
    score = score_metric_association(gold, document)

    report = {
        "mode": "offline_saved_checkpoint_rescore",
        "external_calls": 0,
        "checkpoint": str(checkpoint),
        "benchmark_id": "CAT-GOLD-A",
        "original_metric_association": (result.get("gold_score") or {}).get("metric_association"),
        "normalized_metric_association": score,
        "scientific_record_modified": False,
        "gold_record_modified": False,
    }
    output_path = checkpoint / "gold_a_offline_rescore.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== GOLD A OFFLINE RESCORE ===")
    print("Checkpoint:", checkpoint)
    print("External calls: 0")
    original = report["original_metric_association"] or {}
    print(
        "Original metric association:",
        f"{original.get('matched_count')}/{original.get('expected_count')}",
    )
    print(
        "Normalized metric association:",
        f"{score.get('matched_count')}/{score.get('expected_count')}",
    )
    for item in score.get("results", []):
        print(
            "PASS" if item.get("matched") else "FAIL",
            "|",
            json.dumps(item.get("expected"), ensure_ascii=False),
        )
    print("Report:", output_path)


if __name__ == "__main__":
    main()
