from pathlib import Path

from benchmark.mechanical_v1.locked_case import load_locked_case
from benchmark.mechanical_v1.recover_review_g import recover_review_g
from benchmark.mechanical_v1.score_review_g import score_review_g
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, ExtractedDocument
from synthex_platform.extraction.mechanical_review_guard import (
    apply_mechanical_review_ownership_guard,
    is_explicit_pure_mechanical_review,
)
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext


def _bundle(text: str) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(source_id="review-test", filename="review.pdf", source_checksum="0" * 64),
        pages=[SourcePageContext(
            page=1, native_text=text, text=text, native_parser="pymupdf",
            parser="pymupdf", sufficient=True,
        )],
    )


def test_review_g_locked_offline_control_passes_all_assertions():
    _, gold, lock = load_locked_case("MECH-REVIEW-G")
    archive, guarded, route = recover_review_g()
    score = score_review_g(archive, guarded, route, gold)
    assert score["passed"] == score["total"] == lock["assertions"] == 11
    assert not archive.experiments and not archive.calculations
    assert score["analytics_contamination_count"] == 0
    assert score["graph_contamination_count"] == 0


def test_review_guard_requires_label_and_author_self_description():
    assert is_explicit_pure_mechanical_review(_bundle("Review\nThis paper presents a comprehensive review of tensile properties."))
    assert not is_explicit_pure_mechanical_review(_bundle("This review summarizes prior work before our tensile experiment."))


def test_review_guard_contains_focal_provider_objects_without_losing_evidence():
    text = "Review\nThis review summarizes tensile results. Prior work reported 200 MPa."
    evidence = Evidence(page=1, source_type="text", text_snippet="Prior work reported 200 MPa.")
    draft = ExtractedDocument(
        materials=[DraftMaterial(local_id="m", name="alloy", ownership="focal_work", evidence=[evidence])],
        experiments=[DraftExperiment(
            local_id="e", experiment_type="tensile", material_refs=["m"], ownership="focal_work",
            evidence=[evidence], outputs=[Measurement(
                property="yield_strength", raw_value="200 MPa", value=200, unit="MPa",
                conditions={"scientific_type": "reported_measurement"}, evidence=[evidence],
            )],
        )],
    )
    guarded = apply_mechanical_review_ownership_guard(draft, _bundle(text))
    candidate = guarded.domain_values["mechanical_review"]["noncanonical_candidates"][1]
    assert guarded.materials[0].ownership == "review_summary"
    assert guarded.experiments[0].ownership == "review_summary"
    assert candidate["ownership"] == "review_summary"
    assert candidate["raw_object"]["outputs"][0]["evidence"][0]["text_snippet"]
