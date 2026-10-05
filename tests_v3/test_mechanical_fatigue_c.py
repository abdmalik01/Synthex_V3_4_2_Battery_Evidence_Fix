from __future__ import annotations

from hashlib import sha256

import pytest

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_fatigue_c import recover_fatigue_c
from benchmark.mechanical_v1.score_fatigue_c import score_fatigue_c
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle


@pytest.fixture(scope="module")
def fatigue_case():
    source, gold, lock = load_locked_case("MECH-FATIGUE-C")
    archive, recovered = recover_fatigue_c()
    return source, gold, lock, archive, recovered


def test_fatigue_primary_source_and_reviewed_gold_are_frozen(fatigue_case):
    source, gold, lock, _, _ = fatigue_case
    assert sha256(source.read_bytes()).hexdigest() == lock["source_sha256"]
    assert gold["assertion_count"] == lock["assertions"] == 20
    assert gold["gold_basis"]["tables"] == ["Table A1", "Table A2"]


def test_fatigue_recovery_scores_points_and_preserves_censoring(fatigue_case):
    _, gold, _, archive, recovered = fatigue_case
    score = score_fatigue_c(archive, gold)
    assert (score["passed"], score["total"]) == (20, 20)
    assert score["association_accuracy"] == score["source_tracking"] == 1.0
    assert score["runout_correctness"] == 1.0
    assert len(archive.experiments) == len(recovered) == 60
    assert sum(row["outcome"] == "runout" for row in recovered) == 19
    assert sum(output.property == "cycles_to_failure" for experiment in archive.experiments
               for output in experiment.outputs) == 41
    assert not any(output.property == "fatigue_limit" for experiment in archive.experiments
                   for output in experiment.outputs)
    assert all("bbox=" in row["locator"] and row["table_id"].startswith("tbl-") for row in recovered)
    assert not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def test_fatigue_duplicate_amplitude_failure_and_runout_are_distinct(fatigue_case):
    _, gold, _, archive, _ = fatigue_case
    matched = [experiment for experiment in archive.experiments if (
        any(output.raw_value == "227.26" for output in experiment.outputs)
    )]
    assert len(matched) == 2
    assert sorted(len(experiment.outputs) for experiment in matched) == [1, 2]
    altered = archive.model_copy(deep=True)
    runout = next(experiment for experiment in altered.experiments if (
        len(experiment.outputs) == 1 and experiment.outputs[0].raw_value == "227.26"
    ))
    runout.outputs[0].conditions["failure_or_runout"] = "failure"
    score = score_fatigue_c(altered, gold)
    assert score["passed"] < 20
    assert score["runout_correctness"] < 1.0


def test_fatigue_locked_source_routes_to_mechanical(fatigue_case):
    source, _, _, _, _ = fatigue_case
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    route = DomainRouter().route_text(bundle.page_marked_text())
    assert route.domain == "mechanical"
    assert "fatigue_testing" in route.paper_types
