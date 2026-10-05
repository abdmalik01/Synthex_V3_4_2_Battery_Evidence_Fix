from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_post_e import recover_post_e
from benchmark.additive_manufacturing_v1.score_post_e import score_post_e


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def test_post_e_source_and_gold_are_locked_before_live():
    lock = json.loads((CASE / "post_e_source_lock.json").read_text(encoding="utf-8"))
    assert lock["locked_before_provider_call"] is True
    assert lock["provider_calls_at_lock"] == 0
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_post_e_preserves_eight_directional_treatment_lineages():
    gold = json.loads((CASE / "post_e_gold.json").read_text(encoding="utf-8"))
    archive, rows = recover_post_e()
    score = score_post_e(archive, gold)
    assert len(rows) == score["passed"] == score["total"] == 8
    assert score["mechanical_value_count"] == score["analytics_rows"] == 24
    assert score["experiments"] == 8 and score["calculations"] == 0
    assert score["scientific_safety"] == {
        "as_built_has_no_post_process": True,
        "treatment_identities_distinct": True,
        "mechanical_vocabulary_reused": True,
        "no_am_mechanical_duplicates": True,
        "quarantine_count": 0,
    }
