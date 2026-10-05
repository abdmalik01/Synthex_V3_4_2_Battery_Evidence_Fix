from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_compute_f import recover_compute_f
from benchmark.additive_manufacturing_v1.score_compute_f import score_compute_f


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def test_compute_f_source_and_gold_are_locked_without_provider_call():
    lock = json.loads((CASE / "compute_f_source_lock.json").read_text(encoding="utf-8"))
    assert lock["locked_before_provider_call"] is True
    assert lock["provider_calls_at_lock"] == 0
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_compute_f_keeps_predictions_in_calculation_records():
    gold = json.loads((CASE / "compute_f_gold.json").read_text(encoding="utf-8"))
    archive, rows = recover_compute_f()
    score = score_compute_f(archive, gold)
    assert len(rows) == score["passed"] == score["total"] == 2
    assert score["calculations"] == score["analytics_rows"] == 2
    assert score["experiments"] == score["processes"] == 0
    assert score["scientific_safety"] == {
        "calculation_records_only": True,
        "predicted_not_promoted_to_measured": True,
        "measured_values_are_validation_context_only": True,
        "melt_pool_depth_not_invented": True,
        "quarantine_count": 0,
    }
