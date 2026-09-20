from __future__ import annotations

from pathlib import Path

import pytest

from synthex_platform.benchmarks.corrosion_controls import (
    audit_corrosion_negative_control,
    audit_corrosion_review_control,
)
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.corrosion_review_guard import (
    apply_corrosion_review_ownership_guard,
    is_explicit_pure_review,
)
from synthex_platform.extraction.source_context import (
    SourceBundle,
    SourceMetadata,
    SourcePageContext,
)
from synthex_platform.visual.analytics.projection import project_archives


REPO_ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def review_audit():
    return audit_corrosion_review_control(REPO_ROOT)


@pytest.fixture(scope="module")
def negative_audit():
    return audit_corrosion_negative_control(REPO_ROOT)


def _bundle(text: str) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-review-test",
            filename="review-test.pdf",
            source_checksum="0" * 64,
        ),
        pages=[SourcePageContext(
            page=1,
            native_text=text,
            text=text,
            native_parser="pymupdf",
            parser="pymupdf",
            sufficient=True,
        )],
    )


def test_corr_review_g_is_owned_as_noncanonical_review_content(review_audit):
    assert review_audit["route"] == "corrosion"
    assert review_audit["review_classification"] == "explicit_review"
    assert review_audit["canonical_experiments"] == 0
    assert review_audit["canonical_calculations"] == 0
    assert review_audit["admitted_metrics"] == 0
    assert review_audit["noncanonical_candidate_count"] == 23
    assert review_audit["cited_numeric_candidate_count"] == 21
    assert review_audit["review_table_count"] == 2
    assert review_audit["ownership_violations"] == 0
    assert review_audit["evidence_violations"] == 0
    assert review_audit["graph_contamination_count"] == 0
    assert review_audit["analytics_contamination_count"] == 0
    assert review_audit["score"]["passed"] == review_audit["score"]["total"] == 11
    assert review_audit["score"]["overall"] == 1.0


def test_explicit_review_guard_blocks_focal_experiment_and_calculation_leakage():
    text = """Review
This review summarizes corrosion results.
Steel had a corrosion rate of 2 mm/year. EHOMO was -5.1 eV.
"""
    bundle = _bundle(text)
    document = CorrosionDocument.model_validate({
        "source": {"title": "Review test"},
        "materials": [{
            "local_id": "steel",
            "reported_name": "Steel",
            "ownership": "focal_work",
            "evidence": [{"page": 1, "text_snippet": "Steel", "source_type": "text"}],
        }],
        "experiments": [{
            "experiment_id": "exp-1",
            "experiment_type": "weight_loss",
            "material_refs": ["steel"],
            "ownership": "focal_work",
            "evidence": [{"page": 1, "text_snippet": "corrosion rate", "source_type": "text"}],
            "metrics": [{
                "property": "corrosion_rate",
                "quantity": {"raw_value": "2 mm/year", "value": 2, "unit": "mm/year"},
                "ownership": "focal_work",
                "evidence": [{"page": 1, "text_snippet": "2 mm/year", "source_type": "text"}],
            }],
        }],
        "calculations": [{
            "calculation_id": "calc-1",
            "calculation_type": "dft",
            "material_refs": ["steel"],
            "ownership": "focal_work",
            "evidence": [{"page": 1, "text_snippet": "EHOMO", "source_type": "text"}],
            "outputs": [{
                "property": "homo_energy",
                "quantity": {"raw_value": "-5.1 eV", "value": -5.1, "unit": "eV"},
                "ownership": "focal_work",
                "evidence": [{"page": 1, "text_snippet": "-5.1 eV", "source_type": "text"}],
            }],
        }],
    })

    guarded = apply_corrosion_review_ownership_guard(document, bundle)
    verified = verify_corrosion_document_evidence(guarded, bundle)
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)

    assert is_explicit_pure_review(bundle) is True
    assert guarded.materials[0].ownership == "review_summary"
    assert guarded.experiments[0].ownership == "review_summary"
    assert guarded.experiments[0].metrics[0].ownership == "review_summary"
    assert guarded.calculations[0].ownership == "review_summary"
    assert guarded.calculations[0].outputs[0].ownership == "review_summary"
    assert archive.experiments == []
    assert archive.calculations == []
    assert not project_archives([archive])
    assert not [item for item in archive.relationships if item.predicate != "reported_by"]


def test_review_like_intro_does_not_activate_whole_document_guard():
    bundle = _bundle(
        "This review summarizes the background before the authors report an original experiment."
    )
    document = CorrosionDocument.model_validate({
        "source": {"title": "Mixed original article"},
        "materials": [{
            "local_id": "steel",
            "reported_name": "steel",
            "ownership": "focal_work",
        }],
    })
    guarded = apply_corrosion_review_ownership_guard(document, bundle)

    assert is_explicit_pure_review(bundle) is False
    assert guarded.review_context is None
    assert guarded.materials[0].ownership == "focal_work"


def test_corr_negative_h_routes_to_true_domain_without_corrosion_contamination(negative_audit):
    assert negative_audit["route"] == "batteries"
    assert negative_audit["scores"]["batteries"] > negative_audit["scores"]["corrosion"]
    assert negative_audit["matched_corrosion_terms"]
    assert negative_audit["focal_corrosion_signals"] == []
    assert negative_audit["canonical_experiments"] == 0
    assert negative_audit["canonical_calculations"] == 0
    assert negative_audit["admitted_corrosion_metrics"] == 0
    assert negative_audit["graph_contamination_count"] == 0
    assert negative_audit["score"]["passed"] == negative_audit["score"]["total"] == 9
    assert negative_audit["score"]["overall"] == 1.0
    assert negative_audit["provider_calls"] == 0
