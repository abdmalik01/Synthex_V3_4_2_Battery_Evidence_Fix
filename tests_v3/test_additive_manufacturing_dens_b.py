from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.recover_dens_b import recover_dens_b
from benchmark.additive_manufacturing_v1.score_dens_b import score_dens_b


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def test_dens_b_source_and_gold_locked_before_live():
    lock = json.loads((CASE / "dens_b_source_lock.json").read_text(encoding="utf-8"))
    assert lock["locked_before_provider_call"] is True
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_dens_b_offline_scores_nine_rows_without_density_conflation():
    gold = json.loads((CASE / "dens_b_gold.json").read_text(encoding="utf-8"))
    archive, rows = recover_dens_b()
    score = score_dens_b(archive, gold)
    assert len(rows) == score["passed"] == score["total"] == 9
    assert score["materials"] == 10
    assert score["processes"] == score["experiments"] == score["analytics_rows"] == 9
    assert score["scientific_safety"] == {"relative_density_not_converted": True, "reported_ved_only": True, "defect_identities_distinct": True, "quarantine_count": 0}
