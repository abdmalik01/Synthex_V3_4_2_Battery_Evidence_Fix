from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from benchmark.photovoltaics_v1.closure_audit import run_closure_audit
from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.extraction.photovoltaics_contract import photovoltaics_admission_decision
from synthex_platform.extraction.photovoltaics_review_guard import (
    is_explicit_pure_photovoltaics_review,
)
from synthex_platform.extraction.source_context import (
    SourceBundle,
    SourceMetadata,
    SourcePageContext,
)


CASE = Path(__file__).resolve().parents[1] / "benchmark/photovoltaics_v1"


def _bundle(text: str) -> SourceBundle:
    return SourceBundle(
        source=SourceMetadata(
            source_id="pv-review-test", filename="review.pdf", source_checksum="0" * 64,
        ),
        pages=[SourcePageContext(
            page=1, native_text=text, text=text, native_parser="pymupdf",
            parser="pymupdf", sufficient=True,
        )],
    )


def _measurement(property_name: str, scientific_type: str, unit: str) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value="18.5",
        value=18.5,
        unit=unit,
        conditions={
            "scientific_type": scientific_type,
            "illumination_spectrum": "AM1.5G",
            "irradiance": 100.0,
        },
        evidence=[Evidence(
            page=1, source_type="table", verbatim_match=True,
            text_snippet="18.5", table_id="table-1", locator="row=1;column=value",
        )],
    )


@pytest.fixture(scope="module")
def closure() -> dict:
    return run_closure_audit(write_output=False)


def test_compute_review_negative_and_mixed_sources_and_gold_are_checksum_locked():
    for lock_name in (
        "compute_e_source_lock.json",
        "review_f_source_lock.json",
        "negative_g_source_lock.json",
        "mixed_h_source_lock.json",
    ):
        lock = json.loads((CASE / lock_name).read_text(encoding="utf-8"))
        assert sha256((CASE / lock["source_file"]).read_bytes()).hexdigest() == lock["source_sha256"]
        assert sha256((CASE / lock["gold_file"]).read_bytes()).hexdigest() == lock["gold_sha256"]


def test_all_eight_offline_cases_pass_frozen_gold(closure):
    assert closure["case_assertions"] == {"passed": 57, "total": 57}
    assert len(closure["case_summary"]) == 8
    assert all(item["status"] == "PASS_OFFLINE" for item in closure["case_summary"])
    assert all(item["provider_invoked"] is False for item in closure["case_summary"])


def test_compute_case_is_calculation_only_and_analytics_are_computational(closure):
    compute = next(item for item in closure["case_summary"] if item["case_id"] == "PV-COMPUTE-E")
    assert compute["passed"] == compute["total"] == 8
    assert closure["analytics_safety"]["computational_rows_marked"] is True


def test_property_modality_contract_rejects_cross_admission():
    simulated = _measurement("simulated_power_conversion_efficiency", "simulation_result", "%")
    measured = _measurement("power_conversion_efficiency", "reported_measurement", "%")
    assert photovoltaics_admission_decision(
        simulated, role="result", modality="experimental",
    ).reason == "property_not_allowed_for_experimental"
    assert photovoltaics_admission_decision(
        measured, role="result", modality="computational",
    ).reason == "property_not_allowed_for_computational"


def test_review_guard_requires_publisher_label_and_independent_self_description():
    assert is_explicit_pure_photovoltaics_review(_bundle(
        "Review\nThis review focuses on advances in perovskite solar cells.",
    ))
    assert not is_explicit_pure_photovoltaics_review(_bundle(
        "This review summarizes background before our original solar-cell experiment.",
    ))
    assert not is_explicit_pure_photovoltaics_review(_bundle(
        "Review\nWe fabricated and tested a new photovoltaic device.",
    ))


def test_review_and_negative_controls_have_zero_canonical_analytics_contamination(closure):
    assert closure["analytics_safety"]["review_values_absent"] is True
    assert closure["analytics_safety"]["negative_case_absent"] is True
    assert closure["contamination"] == {
        "ownership": 0,
        "evidence_violations": 0,
        "cross_record_leakage": 0,
        "analytics": 0,
    }


def test_mixed_case_preserves_modalities_and_device_association(closure):
    mixed = next(item for item in closure["case_summary"] if item["case_id"] == "PV-MIXED-H")
    assert mixed["passed"] == mixed["total"] == 10
    assert closure["analytics_safety"]["mixed_modalities_separate"] is True
    invariant = {
        item["id"]: item["passed"] for item in closure["scientific_invariants"]["results"]
    }
    assert invariant["cross_modality_values_tied_to_correct_device"] is True


def test_closure_passes_all_35_scientific_invariants(closure):
    assert closure["scientific_invariants"]["passed"] == 35
    assert closure["scientific_invariants"]["total"] == 35
    assert all(item["passed"] for item in closure["scientific_invariants"]["results"])
    assert closure["readiness"] == "READY_TO_FREEZE_DETERMINISTIC_PV_V1"
    assert closure["raw_gemini_photovoltaics_production_ready"] is False


def test_locked_live_statuses_are_preserved_as_unavailable_not_zero(closure):
    for case_id in ("PV-GOLD-A", "PV-SPEC-B"):
        status = closure["provider_status"][case_id]
        assert status["status"] == "LIVE_UNAVAILABLE_AFTER_RETRIES"
        assert status["attempts"] == 3
        assert status["payload_returned"] is False
        assert status["raw_score"] is None
        assert status["rerun_in_closure"] is False
