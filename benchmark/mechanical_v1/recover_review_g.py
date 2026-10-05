"""Source-locked offline ownership recovery for MECH-REVIEW-G."""

from __future__ import annotations

import pymupdf

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument
from synthex_platform.extraction.mechanical_evidence import verify_mechanical_document_evidence
from synthex_platform.extraction.mechanical_review_guard import apply_mechanical_review_ownership_guard
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext

from .locked_case import load_locked_case


def recover_review_g():
    source, gold, lock = load_locked_case("MECH-REVIEW-G")
    with pymupdf.open(source) as document:
        if len(document) != gold["source"]["page_count"]:
            raise ValueError("Review PDF page count differs from source lock")
        pages = [
            SourcePageContext(
                page=number,
                native_text=document[number - 1].get_text(),
                text=document[number - 1].get_text(),
                native_parser="pymupdf",
                parser="pymupdf",
                sufficient=True,
            )
            for number in (1, 42)
        ]
        full_text = "\n".join(page.get_text() for page in document)
    route = DomainRouter().route_text(full_text)
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id="src-mech-review-g",
            filename=source.name,
            source_checksum=lock["source_sha256"],
        ),
        pages=pages,
    )
    snippet = (
        "The hardness was found to be 54 HV, the yield strength as 60 MPa, ultimate\n"
        "tensile strength of 130 MPa and the elongation of 15%."
    )
    material_evidence = Evidence(
        page=42, source_type="text", original_source_type="native_text",
        verbatim_match=True, text_snippet=snippet,
    )
    value_evidence = Evidence(
        page=42, source_type="text", original_source_type="native_text",
        verbatim_match=True, text_snippet=snippet,
    )
    example = gold["reviewed_noncanonical_example"]
    draft = ExtractedDocument(
        source=DraftSource(
            title=gold["source"]["title"], doi=gold["source"]["doi"],
            url=gold["source"]["url"], year=gold["source"]["year"],
            authors=gold["source"]["authors"],
        ),
        materials=[DraftMaterial(
            local_id="review_aa6061", name=example["material"],
            ownership="focal_work", evidence=[material_evidence],
        )],
        experiments=[DraftExperiment(
            local_id="review_uddinetal_168", experiment_type="reviewed_hardness_report",
            material_refs=["review_aa6061"], ownership="focal_work", evidence=[value_evidence],
            outputs=[Measurement(
                property=example["property"], raw_value=example["raw_value"],
                value=example["value"], unit=example["unit"],
                conditions={
                    "scientific_type": "reported_measurement",
                    "reported_term": "hardness",
                    "data_kind": "scalar",
                    "curve_role": "scalar",
                },
                evidence=[value_evidence],
            )],
        )],
    )
    guarded = apply_mechanical_review_ownership_guard(draft, bundle)
    verified = verify_mechanical_document_evidence(guarded, bundle)
    archive = assemble_archive(verified, domain="mechanical", model="deterministic_review_guard")
    return archive, guarded, route
