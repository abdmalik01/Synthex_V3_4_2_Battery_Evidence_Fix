from __future__ import annotations

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.domain_extractor import DomainGeminiExtractor
from synthex_platform.extraction.draft_models import (
    DraftCalculation,
    DraftExperiment,
    DraftMaterial,
    DraftProcess,
    DraftSource,
    ExtractedDocument,
)
from synthex_platform.extraction.mechanical_contract import (
    MECHANICAL_PROPERTIES,
    mechanical_admission_decision,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.visual.analytics.projection import project_archives
from benchmark.mechanical_v1.score_gold_a import score_archive as score_mechanical_gold_a
import pytest


def _evidence(text: str, *, source_type: str = "table", **updates) -> Evidence:
    payload = {
        "page": 3,
        "source_type": source_type,
        "original_source_type": "table_reported" if source_type == "table" else "native_text",
        "verbatim_match": True,
        "text_snippet": text,
    }
    payload.update(updates)
    return Evidence(**payload)


def _measurement(
    property_name: str,
    raw_value: str,
    value: float,
    unit: str | None,
    *,
    scientific_type: str = "reported_measurement",
    conditions: dict | None = None,
    evidence: list[Evidence] | None = None,
) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=raw_value,
        value=value,
        unit=unit,
        conditions={"scientific_type": scientific_type, **(conditions or {})},
        evidence=evidence or [_evidence(f"The reported value was {raw_value}.")],
    )


def _focal_draft(*, outputs: list[Measurement], calculations: list[DraftCalculation] | None = None) -> ExtractedDocument:
    material_evidence = _evidence("The focal alloy was solution-treated Alloy X.", source_type="text")
    experiment_evidence = _evidence("Tensile tests were conducted on Alloy X.", source_type="text")
    return ExtractedDocument(
        source=DraftSource(title="Condition-resolved mechanical study"),
        materials=[DraftMaterial(
            local_id="alloy_x", name="Alloy X", ownership="focal_work", evidence=[material_evidence]
        )],
        processes=[DraftProcess(
            local_id="solution_treatment",
            name="solution treatment",
            family="heat treatment",
            material_refs=["alloy_x"],
            parameters=[Measurement(
                property="solution_temperature", raw_value="1050 °C", value=1050, unit="°C",
                evidence=[_evidence("solution-treated at 1050 °C", source_type="text")],
            )],
            ownership="focal_work",
            evidence=[material_evidence],
        )],
        experiments=[DraftExperiment(
            local_id="tensile_1",
            experiment_type="tensile_test",
            material_refs=["alloy_x"],
            conditions=[Measurement(
                property="temperature", raw_value="25 °C", value=25, unit="°C",
                evidence=[_evidence("tested at 25 °C", source_type="text")],
            )],
            outputs=outputs,
            ownership="focal_work",
            evidence=[experiment_evidence],
        )],
        calculations=calculations or [],
    )


def test_manifest_defines_v1_families_conditions_and_distinct_hardness_scales():
    spec = DomainRegistry().get("mechanical")
    keys = {item["key"] for item in spec["properties"]}
    assert {
        "yield_strength", "ultimate_tensile_strength", "fracture_strength",
        "vickers_hardness", "rockwell_hardness", "brinell_hardness",
        "creep_strain", "minimum_creep_rate", "rupture_time",
        "cycles_to_failure", "stress_ratio", "crack_growth_rate",
        "fracture_toughness", "j_integral", "ctod",
    } <= keys
    assert "hardness" not in keys
    assert "scientific_type" in spec["condition_vocabulary"]
    assert "series_origin" in spec["condition_vocabulary"]
    assert keys == set(MECHANICAL_PROPERTIES)


def test_prompt_exposes_the_mechanical_scientific_contract_without_provider_call():
    extractor = object.__new__(DomainGeminiExtractor)
    extractor.registry = DomainRegistry()
    prompt = extractor.build_prompt("Tensile source text", "mechanical")
    assert '"scientific_contract"' in prompt
    assert "never use generic hardness" in prompt
    assert "reported_derived_metric" in prompt
    assert "never manufacture curve points" not in prompt  # manifest wording is authoritative


def test_router_requires_specific_mechanical_combinations_and_classifies_paper_type():
    tensile = DomainRouter().route_text(
        "We tested the alloy by a uniaxial tensile test. Yield strength, ultimate tensile strength, "
        "elongation at break, and the stress-strain curve were measured at 25 °C."
    )
    assert tensile.domain == "mechanical"
    assert "tensile_context" in tensile.focal_signals["mechanical"]
    assert "tensile_testing" in tensile.paper_types

    fatigue = DomainRouter().route_text(
        "Fatigue tests were conducted at R = 0.1. The S-N curve reports stress amplitude and cycles to failure."
    )
    assert fatigue.domain == "mechanical"
    assert "fatigue_testing" in fatigue.paper_types

    weak = DomainRouter().route_text(
        "A lithium-ion battery cathode, anode, and electrolyte were evaluated by charge-discharge cycling. "
        "The cell experienced stress, strain, load, resistance, and eventual failure during service."
    )
    assert weak.domain == "batteries"


def test_additively_manufactured_alloy_keeps_am_signals_but_routes_focal_mechanical_study():
    route = DomainRouter().route_text(
        "Laser powder bed fusion additive manufacturing produced the alloy. We tested LPBF specimens "
        "in a tensile test and measured yield strength, ultimate tensile strength, and elongation at break."
    )
    assert route.domain == "mechanical"
    assert "laser powder bed fusion" in route.matched_terms["additive_manufacturing"]
    assert route.scores["additive_manufacturing"] > 0


def test_mechanical_assembly_preserves_conditions_process_lineage_and_input_draft():
    output = _measurement(
        "yield_strength", "512 MPa", 512, "MPa",
        conditions={"specimen_orientation": "longitudinal", "strain_rate": "1e-3 s^-1"},
        evidence=[_evidence("The longitudinal yield strength was 512 MPa.")],
    )
    draft = _focal_draft(outputs=[output])
    before = draft.model_dump(mode="json")

    archive = assemble_archive(draft, domain="mechanical", model="offline-test")
    rows = project_archives([archive])

    assert draft.model_dump(mode="json") == before
    assert len(archive.experiments) == 1
    assert len(rows) == 1
    assert rows[0].property_name == "yield_strength"
    assert rows[0].conditions["temperature"] == 25
    assert rows[0].conditions["specimen_orientation"] == "longitudinal"
    assert rows[0].conditions["scientific_type"] == "reported_measurement"
    assert rows[0].conditions["synthesis_solution_temperature"] == 1050
    assert rows[0].conditions["synthesis_solution_temperature_unit"] == "°C"


def test_hardness_scale_and_unit_safeguards_quarantine_only_invalid_outputs():
    outputs = [
        _measurement("vickers_hardness", "310 HV", 310, "HV"),
        _measurement("hardness", "31 HRC", 31, "HRC"),
        _measurement("yield_strength", "500 HV", 500, "HV"),
        _measurement("rockwell_hardness", "310 HV", 310, "HV"),
    ]
    archive = assemble_archive(_focal_draft(outputs=outputs), domain="mechanical", model="offline-test")
    assert [item.property for item in archive.experiments[0].outputs] == ["vickers_hardness"]
    quarantined = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    reasons = {item["reason"] for item in quarantined if item["kind"] == "measurement"}
    assert reasons == {"ambiguous_hardness_scale", "incompatible_unit"}


def test_curve_points_require_source_series_provenance_but_scalars_do_not_generate_points():
    scalar = _measurement("fatigue_strength", "285 MPa", 285, "MPa")
    table_point = _measurement(
        "cycles_to_failure", "125000 cycles", 125000, "cycles",
        conditions={
            "curve_role": "curve_point", "data_kind": "series_point", "series_id": "sn_table_2", "series_origin": "source_table",
            "stress_amplitude": {"value": 300, "unit": "MPa", "raw_value": "300 MPa"},
        },
    )
    missing_origin = _measurement(
        "cycles_to_failure", "89000 cycles", 89000, "cycles",
        conditions={"curve_role": "curve_point", "data_kind": "series_point", "stress_amplitude": 320},
    )
    archive = assemble_archive(
        _focal_draft(outputs=[scalar, table_point, missing_origin]),
        domain="mechanical",
        model="offline-test",
    )
    outputs = archive.experiments[0].outputs
    assert [item.raw_value for item in outputs] == ["285 MPa", "125000 cycles"]
    assert outputs[0].conditions.get("curve_role") is None
    rows = project_archives([archive])
    assert len(rows) == 2
    point = next(row for row in rows if row.property_name == "cycles_to_failure")
    assert point.conditions["stress_amplitude"] == 300
    assert point.conditions["stress_amplitude_unit"] == "MPa"
    quarantined = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    assert any(item["reason"] == "curve_point_missing_source_series_provenance" for item in quarantined)


def test_explicit_figure_digitization_requires_matching_figure_provenance():
    conditions = {
        "curve_role": "curve_point", "data_kind": "series_point", "series_id": "curve_3", "series_origin": "figure_digitized"
    }
    unverified = _measurement("stress", "401 MPa", 401, "MPa", conditions=conditions)
    assert mechanical_admission_decision(unverified, modality="experimental").reason == "figure_digitization_not_canonical"

    verified = _measurement(
        "stress", "401 MPa", 401, "MPa", conditions=conditions,
        evidence=[_evidence(
            "Digitized point 401 MPa", source_type="figure", figure_id="fig-3",
            original_source_type="figure_digitized",
        )],
    )
    assert mechanical_admission_decision(verified, modality="experimental").reason == "figure_digitization_not_canonical"


def test_mechanical_numeric_and_series_metadata_guards():
    mismatched = _measurement("yield_strength", "500 MPa", 600, "MPa")
    assert mechanical_admission_decision(mismatched, modality="experimental").reason == "parsed_value_mismatch"
    point_without_kind = _measurement(
        "stress", "401 MPa", 401, "MPa",
        conditions={"curve_role": "curve_point", "series_id": "table_1", "series_origin": "source_table"},
    )
    assert mechanical_admission_decision(point_without_kind, modality="experimental").reason == "inconsistent_curve_data_kind"
    wrong_unit = _measurement("fracture_toughness", "40 MPa", 40, "MPa")
    assert mechanical_admission_decision(wrong_unit, modality="experimental").reason == "incompatible_unit"


def test_mechanical_missing_sample_association_is_quarantined():
    draft = _focal_draft(outputs=[_measurement("yield_strength", "512 MPa", 512, "MPa")])
    draft.experiments[0].material_refs = []
    archive = assemble_archive(draft, domain="mechanical", model="offline-test")
    assert archive.experiments == []
    reasons = {item["reason"] for item in archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]}
    assert "ambiguous_or_missing_material_association" in reasons


def test_reported_derived_and_model_predictions_remain_in_separate_record_types():
    modulus = _measurement(
        "youngs_modulus", "205 GPa", 205, "GPa",
        scientific_type="reported_derived_metric",
        evidence=[_evidence("The fitted Young's modulus was 205 GPa.")],
    )
    prediction = _measurement(
        "yield_strength", "prediction: 540 MPa", 540, "MPa",
        scientific_type="model_prediction",
        evidence=[_evidence("The model prediction was prediction: 540 MPa.", source_type="text")],
    )
    calc_evidence = _evidence("The model prediction was prediction: 540 MPa.", source_type="text")
    calculation = DraftCalculation(
        local_id="model_1",
        calculation_type="constitutive_model_prediction",
        material_refs=["alloy_x"],
        method="constitutive model",
        outputs=[prediction],
        ownership="focal_work",
        evidence=[calc_evidence],
    )
    archive = assemble_archive(
        _focal_draft(outputs=[modulus], calculations=[calculation]),
        domain="mechanical",
        model="offline-test",
    )
    rows = project_archives([archive])
    assert {(row.property_name, row.modality) for row in rows} == {
        ("youngs_modulus", "experimental"),
        ("yield_strength", "computational"),
    }
    assert next(row for row in rows if row.modality == "computational").conditions["scientific_type"] == "model_prediction"


def test_value_specific_evidence_and_scientific_type_are_required_for_admission():
    no_value_evidence = _measurement(
        "yield_strength", "500 MPa", 500, "MPa",
        evidence=[_evidence("Yield strength was reported in Table 2.")],
    )
    no_type = Measurement(
        property="yield_strength", raw_value="500 MPa", value=500, unit="MPa",
        evidence=[_evidence("Yield strength was 500 MPa.")],
    )
    assert mechanical_admission_decision(no_value_evidence, modality="experimental").reason == "measurement_value_not_source_evidenced"
    assert mechanical_admission_decision(no_type, modality="experimental").reason == "missing_or_invalid_scientific_type"


def test_gold_a_scorer_requires_source_lock_and_checks_associations_offline():
    output = _measurement(
        "yield_strength", "512 MPa", 512, "MPa",
        conditions={"reported_term": "0.2% proof stress", "strain_rate": "1e-3 s^-1"},
        evidence=[_evidence("The 0.2% proof stress was 512 MPa.")],
    )
    archive = assemble_archive(_focal_draft(outputs=[output]), domain="mechanical", model="offline-test")
    assertion = {
        "property": "yield_strength", "value": 512, "unit": "MPa", "sample": "Alloy X",
        "conditions": {"temperature": 25, "reported_term": "0.2% proof stress"},
        "scientific_type": "reported_measurement", "evidence_text": "512 MPa",
    }
    contract = {
        "case_id": "MECH-GOLD-A", "status": "awaiting_source_lock_and_independent_gold_review",
        "source": {"sha256": None}, "assertions": [assertion],
    }
    with pytest.raises(ValueError, match="locked source"):
        score_mechanical_gold_a(archive, contract)
    # This synthetic contract tests scorer mechanics only; it is not paper-derived gold.
    contract["status"] = "locked_reviewed"
    contract["source"]["sha256"] = "synthetic-test-only"
    result = score_mechanical_gold_a(archive, contract)
    assert (result["passed"], result["total"], result["recall"]) == (1, 1, 1.0)
    contract["assertions"][0]["conditions"]["temperature"] = 500
    assert score_mechanical_gold_a(archive, contract)["passed"] == 0
