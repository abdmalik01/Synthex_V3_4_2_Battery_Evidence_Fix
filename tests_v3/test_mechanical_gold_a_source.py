from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from benchmark.mechanical_v1.recover_table4 import recover_table4
from benchmark.mechanical_v1.score_gold_a import score_archive
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.mechanical_evidence import verify_mechanical_document_evidence
from synthex_platform.extraction.draft_models import DraftMaterial, DraftSource, ExtractedDocument
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.core.models import Evidence


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "benchmark/mechanical_v1"


def test_locked_gold_a_source_and_gold_checksums():
    lock = json.loads((CASE / "source_lock.json").read_text(encoding="utf-8"))
    assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
    assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_table4_recovery_preserves_every_sample_treatment_and_test_row():
    source = CASE / "corpus_pdfs/metals-08-00393.pdf"
    gold = json.loads((CASE / "gold_a_contract.json").read_text(encoding="utf-8"))
    archive, recovered = recover_table4(source, CASE / "gold_a_contract.json")
    score = score_archive(archive, gold)
    assert (score["passed"], score["total"]) == (18, 18)
    assert len(archive.materials) == 3 and len(archive.experiments) == 6
    assert len(archive.calculations) == 0
    assert len({(item["sample"], item["treatment"], item["overaging"], item["test_temperature"]) for item in recovered}) == 6
    assert all(item["table_id"].startswith("tbl-") and "bbox=" in item["locator"] for item in recovered)
    assert not archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def test_gold_a_route_is_mechanical_from_source_text():
    import pymupdf

    with pymupdf.open(CASE / "corpus_pdfs/metals-08-00393.pdf") as document:
        text = "\n".join(page.get_text() for page in document)
    route = DomainRouter().route_text(text)
    assert route.domain == "mechanical"
    assert "tensile_testing" in route.paper_types


def test_provider_verbatim_claim_is_rechecked_against_locked_source():
    bundle = build_source_bundle(
        CASE / "corpus_pdfs/metals-08-00393.pdf", enable_ocr=False, include_figures=False,
    )
    draft = ExtractedDocument(
        source=DraftSource(title="test"),
        materials=[DraftMaterial(
            local_id="test", name="A354", ownership="focal_work",
            evidence=[Evidence(page=15, source_type="text", text_snippet="invented 999 MPa", verbatim_match=True)],
        )],
    )
    verified = verify_mechanical_document_evidence(draft, bundle)
    assert draft.materials[0].evidence[0].verbatim_match is True
    assert verified.materials[0].evidence[0].verbatim_match is False


def test_creep_and_fatigue_specs_point_to_locked_reviewed_gold():
    for filename, case_id, expected_provider_calls in (
        ("creep_b_spec.json", "MECH-CREEP-B", 2),
        ("fatigue_c_spec.json", "MECH-FATIGUE-C", 4),
    ):
        spec = json.loads((CASE / filename).read_text(encoding="utf-8"))
        assert spec["case_id"] == case_id
        assert spec["status"].startswith("locked_offline_validated")
        assert (CASE / spec["source_lock"]).exists()
        assert (CASE / spec["gold"]).exists()
        assert spec["gold_assertions"] > 0
        assert spec["provider_calls"] == expected_provider_calls
        assert spec["required_associations"] and spec["scientific_boundaries"]
