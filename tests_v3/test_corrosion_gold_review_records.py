import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "benchmark" / "corrosion_v1"
GOLD = ROOT / "gold"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixed_benchmark_manual_review_complete_and_holdout_stays_excluded():
    scaffold = _load(ROOT / "gold_assertions_scaffold.json")
    assert scaffold["status"] == "manual_source_review_complete_live_benchmark_pending"

    papers = {item["id"]: item for item in scaffold["papers"]}
    fixed_ids = [
        "CORR-GOLD-A",
        "CORR-COAT-B",
        "CORR-INHIB-C",
        "CORR-EIS-D",
        "CORR-WEIGHT-E",
        "CORR-DFT-F",
        "CORR-REVIEW-G",
        "CORR-NEGATIVE-H",
    ]
    for paper_id in fixed_ids:
        item = papers[paper_id]
        assert item["gold_status"] == "manual_source_review_complete"
        record = ROOT.parent.parent / item["gold_record"]
        assert record.exists(), f"missing gold/control record for {paper_id}"

    holdout = papers["CORR-HOLDOUT-I"]
    assert holdout["gold_status"] == "holdout_not_for_tuning"
    assert "gold_record" not in holdout
    assert not (GOLD / "CORR-HOLDOUT-I.json").exists()


def test_numeric_gold_observations_are_source_grounded():
    for path in sorted(GOLD.glob("CORR-*.json")):
        payload = _load(path)
        for observation in payload.get("scored_numeric_observations", []):
            assert observation.get("metric")
            assert isinstance(observation.get("value"), (int, float))
            assert observation.get("unit")
            assert isinstance(observation.get("page"), int)
            assert observation.get("evidence_snippet")


def test_control_records_preserve_scientific_boundaries():
    dft = _load(GOLD / "CORR-DFT-F.json")
    assert dft["paper_type"] == "computational_corrosion"
    assert dft["required_safety_assertion"]["must_not_admit_as_experimental_performance"] is True
    assert dft["required_safety_assertion"]["expected_focal_experimental_corrosion_observations"] == 0

    review = _load(GOLD / "CORR-REVIEW-G.json")
    assert review["paper_type"] == "review"
    assert review["assertions"]["canonical_focal_experiments_expected"] == 0
    assert review["assertions"]["cited_numeric_results_must_not_be_focal"] is True

    negative = _load(GOLD / "CORR-NEGATIVE-H.json")
    assert negative["routing_contract"]["expected_route"] == "batteries"
    assert negative["routing_contract"]["must_not_route_to"] == "corrosion"
    assert negative["required_safety_assertion"]["corrosion_canonical_observations_expected"] == 0


def test_ambiguous_or_conflicting_source_statements_are_not_silently_collapsed():
    inhibitor = _load(GOLD / "CORR-INHIB-C.json")
    assert inhibitor["source_conflicts_or_cautions"]

    weight = _load(GOLD / "CORR-WEIGHT-E.json")
    assert weight["source_conflicts_or_cautions"]
    primary = weight["scored_numeric_observations"]
    assert any(item["metric"] == "corrosion_rate" and item["value"] == 1.15 for item in primary)
    assert all(not (item["metric"] == "corrosion_rate" and item["value"] == 0.97) for item in primary)
