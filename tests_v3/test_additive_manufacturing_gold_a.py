from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_gold_a import recover_gold_a
from benchmark.additive_manufacturing_v1.score_gold_a import score_gold_a


ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "benchmark" / "additive_manufacturing_v1"


def _read(name: str) -> dict:
    return json.loads((CASE_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_am_gold_a_source_and_gold_are_locked_before_any_provider_call():
    lock = _read("source_lock.json")
    assert lock["provider_calls"] == 0
    assert lock["locked_before_provider_call"] is True
    assert _sha256(CASE_DIR / lock["source_file"]) == lock["source_sha256"]
    assert _sha256(CASE_DIR / lock["gold_file"]) == lock["gold_sha256"]


def test_am_gold_a_offline_recovery_scores_all_rows_and_safety_guards():
    gold = _read("gold_a_contract.json")
    archive, recovered = recover_gold_a()
    score = score_gold_a(archive, gold)
    assert len(recovered) == 27
    assert score["passed"] == score["total"] == 27
    assert score["materials"] == 28
    assert score["processes"] == 54
    assert score["experiments"] == score["analytics_rows"] == 27
    assert score["scientific_safety"] == {
        "relative_density_kept_distinct_from_porosity": True,
        "no_unreported_energy_density": True,
        "analytics_preserve_build_coordinates": True,
        "quarantine_count": 0,
    }
