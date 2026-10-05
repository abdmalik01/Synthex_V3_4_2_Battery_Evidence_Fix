from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.additive_manufacturing_v1.benchmark_common import load_locked
from benchmark.additive_manufacturing_v1.recover_negative_h import recover_negative_h
from benchmark.additive_manufacturing_v1.recover_review_g import recover_review_g
from benchmark.additive_manufacturing_v1.score_negative_h import score_negative_h
from benchmark.additive_manufacturing_v1.score_review_g import score_review_g
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.additive_manufacturing_review_guard import (
    apply_additive_manufacturing_review_ownership_guard,
    is_explicit_pure_additive_manufacturing_review,
)
from synthex_platform.extraction.draft_models import (
    DraftExperiment,
    DraftMaterial,
    ExtractedDocument,
)
from synthex_platform.extraction.source_context import (
    SourceBundle,
    SourceMetadata,
    SourcePageContext,
)


CASE = Path(__file__).resolve().parents[1] / "benchmark/additive_manufacturing_v1"


def _bundle(text: str) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="am-review-test", filename="review.pdf", source_checksum="0" * 64,
        ),
        pages=[SourcePageContext(
            page=1, native_text=text, text=text, native_parser="pymupdf",
            parser="pymupdf", sufficient=True,
        )],
    )


def test_review_and_negative_sources_and_gold_are_locked_without_provider_calls():
    for lock_name in ("review_g_source_lock.json", "negative_h_source_lock.json"):
        lock = json.loads((CASE / lock_name).read_text(encoding="utf-8"))
        assert lock["locked_before_provider_call"] is True
        assert lock["provider_calls_at_lock"] == 0
        assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
        assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_review_g_passes_with_zero_canonical_or_analytics_contamination():
    _, gold, _ = load_locked("review_g_source_lock.json")
    archive, guarded, route = recover_review_g()
    score = score_review_g(archive, guarded, route, gold)
    assert score["passed"] == score["total"] == 11
    assert score["canonical_experiments"] == score["canonical_calculations"] == 0
    assert score["canonical_measurements"] == 0
    assert score["ownership_violations"] == score["evidence_violations"] == 0
    assert score["analytics_contamination_count"] == score["graph_contamination_count"] == 0


def test_review_guard_requires_label_and_independent_self_description():
    assert is_explicit_pure_additive_manufacturing_review(_bundle(
        "Review\nThis work aims to present an overview of coated powders for L-PBF."
    ))
    assert not is_explicit_pure_additive_manufacturing_review(_bundle(
        "This review summarizes background before our original L-PBF experiment."
    ))


def test_review_guard_contains_focal_objects_without_losing_evidence():
    text = "Review\nThis review summarizes L-PBF results. Prior work reported 99.9%."
    evidence = Evidence(
        page=1, source_type="text", verbatim_match=True,
        text_snippet="Prior work reported 99.9%.",
    )
    draft = ExtractedDocument(
        materials=[DraftMaterial(
            local_id="m", name="powder", ownership="focal_work", evidence=[evidence],
        )],
        experiments=[DraftExperiment(
            local_id="e", experiment_type="density", material_refs=["m"],
            ownership="focal_work", evidence=[evidence], outputs=[Measurement(
                property="relative_density", raw_value="99.9%", value=99.9, unit="%",
                conditions={"scientific_type": "reported_measurement"}, evidence=[evidence],
            )],
        )],
    )
    guarded = apply_additive_manufacturing_review_ownership_guard(draft, _bundle(text))
    candidate = guarded.domain_values["additive_manufacturing_review"]["noncanonical_candidates"][1]
    assert guarded.materials[0].ownership == "review_summary"
    assert guarded.experiments[0].ownership == "review_summary"
    assert candidate["ownership"] == "review_summary"
    assert candidate["raw_object"]["outputs"][0]["evidence"][0]["text_snippet"]


def test_negative_h_routes_repeatably_to_batteries_with_zero_am_contamination():
    _, gold, _ = load_locked("negative_h_source_lock.json")
    archive, first, second, text = recover_negative_h()
    score = score_negative_h(archive, first, second, text, gold)
    assert score["passed"] == score["total"] == 10
    assert score["route"] == "batteries"
    assert set(score["misleading_vocabulary_detected"]) == set(gold["misleading_vocabulary"])
    assert not score["focal_am_signals"]
    assert score["canonical_builds"] == score["canonical_experiments"] == 0
    assert score["canonical_calculations"] == score["canonical_metrics"] == 0
    assert score["analytics_contamination_count"] == score["graph_contamination_count"] == 0
