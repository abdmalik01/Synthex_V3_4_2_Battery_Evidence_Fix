import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import DeviceEntity, ExperimentRecord
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_platform.extraction.battery_evidence import verify_battery_evidence
from synthex_platform.extraction.battery_models import (
    BatteryConditionConflict,
    BatteryConflictValue,
    BatteryDocument,
    BatteryEvidence,
    BatteryGroup,
    BatteryMaterial,
    BatteryPerformancePoint,
    BatterySource,
)
from synthex_platform.extraction.battery_postprocess import apply_scientific_guardrails
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text


ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "benchmark" / "batteries_v1" / "corpus_pdfs"
PRIOR_OUTPUTS = ROOT / "benchmark" / "outputs" / "corpus" / "before"


def _point(value, *, ownership="focal_work", evidence=None, **kwargs):
    return BatteryPerformancePoint(
        property="specific_capacity",
        raw_value=f"{value} mAh/g",
        value=value,
        unit="mAh/g",
        ownership=ownership,
        evidence=evidence or [],
        **kwargs,
    )


def test_evidence_verifier_records_normalized_verbatim_match_without_replacing_raw_text():
    raw_snippet = "Capacity was 121.3\u00a0mAh g−1."
    evidence = BatteryEvidence(page=2, section="Results", source_type="text", text_snippet=raw_snippet)
    paraphrase = BatteryEvidence(page=2, source_type="text", text_snippet="The capacity reached about 121.3 mAh/g.")
    doc = BatteryDocument(battery_groups=[BatteryGroup(
        group_id="g1",
        performance_points=[_point(121.3, evidence=[evidence, paraphrase])],
    )])
    source = "--- PAGE 1 ---\nIntroduction\n--- PAGE 2 ---\nCapacity was 121.3 mAh g−1."

    verify_battery_evidence(doc, source)

    checked = doc.battery_groups[0].performance_points[0].evidence
    assert checked[0].verbatim_match is True
    assert checked[0].text_snippet == raw_snippet
    assert checked[0].page == 2
    assert checked[0].section == "Results"
    assert checked[0].source_type == "text"
    assert checked[1].verbatim_match is False


def test_source_type_paragraph_is_bounded_alias_and_arbitrary_values_still_fail():
    evidence = BatteryEvidence.model_validate({
        "page": 1,
        "source_type": "paragraph",
        "text_snippet": "reported in the paragraph",
    })
    assert evidence.source_type == "text"
    assert evidence.original_source_type == "paragraph"

    with pytest.raises(ValidationError, match="source_type"):
        BatteryEvidence.model_validate({"source_type": "narrative_block"})


def test_only_focal_verbatim_supported_quantitative_values_enter_archive():
    source = "--- PAGE 1 ---\nThe focal capacity was 121.3 mAh/g. Prior work reported 99 mAh/g."
    admitted = _point(
        121.3,
        evidence=[BatteryEvidence(page=1, source_type="text", text_snippet="The focal capacity was 121.3 mAh/g.")],
    )
    no_evidence = _point(88.0)
    cited = _point(
        99.0,
        ownership="cited_prior_work",
        evidence=[BatteryEvidence(page=1, source_type="text", text_snippet="Prior work reported 99 mAh/g.")],
    )
    doc = BatteryDocument(
        source=BatterySource(title="Admissibility"),
        battery_groups=[BatteryGroup(
            group_id="g1",
            ownership="focal_work",
            performance_points=[admitted, no_evidence, cited],
        )],
    )

    archive = assemble_battery_archive(doc, model="test", source_text=source)
    outputs = [output for experiment in archive.experiments for output in experiment.outputs]
    audit = archive.domain_payloads[0].values["admissibility"]

    assert [(output.value, output.property) for output in outputs] == [(121.3, "specific_capacity")]
    assert audit["admitted_quantitative_values"] == 1
    assert audit["quarantined_quantitative_values"] == 2
    assert {item["reason"] for item in audit["quarantine"]} == {
        "no_verbatim_evidence",
        "ownership_cited_prior_work",
    }
    assert len(doc.battery_groups[0].performance_points) == 3
    assert any("quarantined" in warning.lower() for warning in archive.quality.semantic_warnings)


@pytest.mark.parametrize(
    ("document_name", "pdf_name", "prior_points"),
    [
        (
            "application_of_first_principles_computations_based_extracted_document.json",
            "Application_of_First_Principles_Computations_Based.pdf",
            10,
        ),
        ("coatings_16_00912_extracted_document.json", "coatings-16-00912.pdf", 33),
    ],
)
def test_prior_review_measurements_do_not_enter_focal_archive(document_name, pdf_name, prior_points):
    raw = json.loads((PRIOR_OUTPUTS / document_name).read_text(encoding="utf-8"))
    doc = BatteryDocument.model_validate(raw)
    source_text = pages_to_marked_text(extract_pages(CORPUS / pdf_name))
    assert sum(len(group.performance_points) for group in doc.battery_groups) == prior_points

    archive = assemble_battery_archive(doc, model="test", source_text=source_text)
    canonical_values = sum(len(experiment.outputs) for experiment in archive.experiments)
    canonical_values += sum(len(calculation.outputs) for calculation in archive.calculations)
    audit = archive.domain_payloads[0].values["admissibility"]

    assert canonical_values == 0
    assert audit["quarantined_quantitative_values"] >= prior_points
    assert any("ownership_unknown" in item["reason"] for item in audit["quarantine"])


def test_conflicted_condition_is_structured_and_not_retained_as_certain():
    conflict = BatteryConditionConflict(
        field="electrochemical_testing.long_term_c_rate",
        reported_values=[
            BatteryConflictValue(value="0.1 C", evidence=[]),
            BatteryConflictValue(value="1 C", evidence=[]),
        ],
        resolved_value=None,
    )
    doc = BatteryDocument(battery_groups=[BatteryGroup(
        group_id="700C",
        ownership="focal_work",
        condition_conflicts=[conflict],
        performance_points=[_point(121.3, c_rate="0.1 C")],
    )])

    guarded = apply_scientific_guardrails(doc)

    assert guarded.battery_groups[0].condition_conflicts[0].field == "c_rate"
    assert guarded.battery_groups[0].condition_conflicts[0].status == "conflicted"
    assert guarded.battery_groups[0].condition_conflicts[0].resolved_value is None
    assert guarded.battery_groups[0].performance_points[0].c_rate is None
    assert any("conflicted c_rate" in note for note in guarded.extraction_notes)


def test_focal_dft_result_is_a_calculation_not_a_cycling_experiment():
    source = "--- PAGE 1 ---\nDFT calculated a migration barrier of 0.30 eV for beta-NaMnO2."
    evidence = BatteryEvidence(
        page=1,
        source_type="text",
        text_snippet="DFT calculated a migration barrier of 0.30 eV for beta-NaMnO2.",
    )
    material = BatteryMaterial(
        material_id="m1",
        formula="NaMnO2",
        role="cathode",
        ownership="focal_work",
        evidence=[evidence],
    )
    point = BatteryPerformancePoint(
        property="migration_energy_barrier",
        raw_value="0.30 eV",
        value=0.30,
        unit="eV",
        method="DFT, PBE+U",
        ownership="focal_work",
        evidence=[evidence],
    )
    doc = BatteryDocument(
        source=BatterySource(title="Focal DFT"),
        paper_types=["computational_dft"],
        materials=[material],
        battery_groups=[BatteryGroup(
            group_id="g1",
            material_ref="m1",
            ownership="focal_work",
            performance_points=[point],
            evidence=[evidence],
        )],
    )

    archive = assemble_battery_archive(doc, model="test", source_text=source)

    assert len(archive.calculations) == 1
    assert archive.calculations[0].outputs[0].property == "migration_energy_barrier"
    assert archive.calculations[0].method == "DFT, PBE+U"
    assert not any(experiment.outputs for experiment in archive.experiments)


def test_corpus_first_principles_shapes_route_focal_dft_values_to_calculations():
    """Exercise real corpus properties/methods while overriding review ownership for routing only."""
    document_path = PRIOR_OUTPUTS / "application_of_first_principles_computations_based_extracted_document.json"
    doc = BatteryDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
    source_text = pages_to_marked_text(
        extract_pages(CORPUS / "Application_of_First_Principles_Computations_Based.pdf")
    )
    expected_dft_values = 0
    for group in doc.battery_groups:
        group.ownership = "focal_work"
        for point in group.performance_points:
            if "dft" in (point.method or "").lower():
                point.ownership = "focal_work"
                expected_dft_values += 1
            else:
                point.ownership = "cited_prior_work"

    archive = assemble_battery_archive(doc, model="test", source_text=source_text)

    assert expected_dft_values == 5
    assert sum(len(calculation.outputs) for calculation in archive.calculations) == expected_dft_values
    assert not any(experiment.outputs for experiment in archive.experiments)
    assert {output.property for calculation in archive.calculations for output in calculation.outputs} == {
        "reaction_voltage", "band_gap", "migration_energy_barrier",
    }


def test_archive_rejects_internal_entity_references_that_do_not_exist():
    with pytest.raises(ValidationError, match="unknown material IDs"):
        SynthexArchive(
            metadata=ArchiveMetadata(archive_id="arc-test"),
            devices=[DeviceEntity(device_id="d1", device_type="battery", material_ids=["missing-mat"])],
        )

    with pytest.raises(ValidationError, match="unknown device IDs"):
        SynthexArchive(
            metadata=ArchiveMetadata(archive_id="arc-test"),
            experiments=[ExperimentRecord(experiment_id="e1", experiment_type="test", device_ids=["missing-device"])],
        )


def test_battery_invalid_material_and_protocol_refs_are_warned_and_removed_from_canonical_refs():
    doc = BatteryDocument(battery_groups=[BatteryGroup(
        group_id="g1",
        material_ref="missing-material",
        protocol_refs=["missing-protocol"],
        ownership="focal_work",
    )])

    archive = assemble_battery_archive(doc, model="test", source_text="--- PAGE 1 ---\nNo values.")

    assert archive.devices[0].material_ids == []
    assert "protocol_refs" not in archive.devices[0].configuration
    assert any("unknown material_ref" in warning for warning in archive.quality.semantic_warnings)
    assert any("unknown protocol_ref" in warning for warning in archive.quality.semantic_warnings)


def test_malformed_font_corpus_pdf_uses_pymupdf_fallback():
    pages = extract_pages(CORPUS / "1-s2.0-S2666386426002407-main.pdf")

    assert len(pages) == 15
    assert pages[0]["parser"] == "pymupdf"
    assert "Predicting battery performance" in pages[0]["text"]
