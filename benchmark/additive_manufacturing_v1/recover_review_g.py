"""Source-locked offline ownership recovery for AM-REVIEW-G."""

from __future__ import annotations

from synthex_platform.core.models import Evidence
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.additive_manufacturing_review_guard import (
    apply_additive_manufacturing_review_ownership_guard,
)
from synthex_platform.extraction.draft_models import (
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle

from .benchmark_common import load_locked, measurement


def recover_review_g():
    source, gold, lock = load_locked("review_g_source_lock.json")
    bundle = build_source_bundle(source, enable_ocr=False, include_figures=False)
    if len(bundle.pages) != gold["source"]["page_count"]:
        raise ValueError("Review PDF page count differs from source lock")
    route = DomainRouter().route_text(bundle.page_marked_text())
    example = gold["reviewed_noncanonical_example"]
    row_evidence = Evidence(
        page=example["page"],
        source_type="table",
        original_source_type="table_reported",
        verbatim_match=True,
        table_id=example["table"],
        locator="row=TiB2_Ref104",
        text_snippet="TiB2; ball milling; Ref. [104]; 100 W; 83.33 mm/s; 50 µm; 99.99%",
    )
    ownership = "cited_prior_work"
    draft = ExtractedDocument(
        source=DraftSource(
            title=gold["source"]["title"],
            doi=gold["source"]["doi"],
            url=gold["source"]["url"],
            year=gold["source"]["year"],
            authors=gold["source"]["authors"],
        ),
        materials=[DraftMaterial(
            local_id="review_fe_tib2",
            name=example["material"],
            tags=["am_feedstock", "review_comparison"],
            ownership=ownership,
            evidence=[row_evidence],
        )],
        processes=[DraftProcess(
            local_id="review_lpbf_ref104",
            name="cited L-PBF build from Ref. [104]",
            family="laser_powder_bed_fusion",
            material_refs=["review_fe_tib2"],
            ownership=ownership,
            evidence=[row_evidence],
            parameters=[
                measurement("laser_power", "100 W", 100, "W", row_evidence, scientific_type="reported_measurement"),
                measurement("scan_speed", "83.33 mm/s", 83.33, "mm/s", row_evidence, scientific_type="reported_measurement"),
                measurement("layer_thickness", "50 µm", 50, "µm", row_evidence, scientific_type="reported_measurement"),
            ],
        )],
        experiments=[DraftExperiment(
            local_id="review_density_ref104",
            experiment_type="reviewed_relative_density_report",
            material_refs=["review_fe_tib2"],
            ownership=ownership,
            evidence=[row_evidence],
            outputs=[measurement(
                example["property"], example["raw_value"], example["value"],
                example["unit"], row_evidence, scientific_type="reported_measurement",
            )],
        )],
    )
    guarded = apply_additive_manufacturing_review_ownership_guard(draft, bundle)
    archive = assemble_archive(
        guarded,
        domain="additive_manufacturing",
        model="deterministic_review_guard",
    )
    return archive, guarded, route
