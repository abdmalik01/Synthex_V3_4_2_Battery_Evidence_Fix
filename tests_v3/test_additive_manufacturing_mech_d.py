from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_mech_d import recover_mech_d
from benchmark.additive_manufacturing_v1.score_mech_d import score_mech_d


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def test_mech_d_source_and_gold_locked_without_provider_call():
    lock = json.loads((CASE / "mech_d_source_lock.json").read_text(encoding="utf-8"))
    assert lock["provider_calls"] == 0
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_mech_d_reuses_mechanical_vocabulary_and_preserves_lineage():
    gold = json.loads((CASE / "mech_d_gold.json").read_text(encoding="utf-8"))
    archive, builds, rows = recover_mech_d()
    score = score_mech_d(archive, gold)
    assert len(builds) == 3
    assert len(rows) == score["passed"] == score["total"] == 12
    assert score["mechanical_value_count"] == score["analytics_rows"] == 36
    assert score["scientific_safety"] == {"mechanical_v1_vocabulary_reused": True, "no_am_mechanical_duplicates": True, "measurements_remain_specimen_scoped": True, "build_and_post_process_separate": True, "test_temperature_not_build_temperature": True, "quarantine_count": 0}
