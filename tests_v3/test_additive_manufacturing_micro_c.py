from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_micro_c import recover_micro_c
from benchmark.additive_manufacturing_v1.score_micro_c import score_micro_c


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def test_micro_c_source_and_gold_locked_without_provider_call():
    lock = json.loads((CASE / "micro_c_source_lock.json").read_text(encoding="utf-8"))
    assert lock["provider_calls"] == 0
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_micro_c_offline_scores_all_samples_and_texture_cells():
    gold = json.loads((CASE / "micro_c_gold.json").read_text(encoding="utf-8"))
    archive, rows = recover_micro_c()
    score = score_micro_c(archive, gold)
    assert len(rows) == score["passed"] == score["total"] == 16
    assert score["value_count"] == score["analytics_rows"] == 80
    assert score["scientific_safety"] == {"texture_is_crystallographic_not_surface": True, "no_phase_fraction_inferred": True, "no_particle_grain_size_conflation": True, "post_process_separate": True, "quarantine_count": 0}
