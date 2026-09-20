from __future__ import annotations

import json
from pathlib import Path

from synthex_platform.benchmarks.corrosion import score_corrosion_archive
from synthex_platform.benchmarks.corrosion_live import expectations_from_gold, load_live_case
from synthex_platform.extraction.corrosion_admission import decide_corrosion_metric_admission
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_models import (
    CorrosionDocument,
    CorrosionEvidence,
    CorrosionMetric,
    CorrosionQuantity,
)
from synthex_platform.extraction.corrosion_table_recovery import recover_corrosion_parameter_tables
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.extraction.source_context import build_source_bundle
from synthex_platform.scientific_text import normalize_scientific_text
from synthex_platform.visual.analytics.projection import project_archives


REPO_ROOT = Path(__file__).parents[1]
TABLE_HEADER = "Time, h Re, Ω Rt, Ω Cdl, Ω−1·sn ndl Rcp, Ω Ccp, Ω−1·sn ncp"
ROW_24 = "24 7.557 13.87 1.506·10−3 0.777 14488 1.483·10−3 0.731"
ROW_2000 = "2000 5.072 6.65 4.440·10−3 0.809 188 1.195·10−2 0.610"


def _bundle() -> SourceBundle:
    text = "\n".join((
        "9Cr-1Mo P91 steel was protected by a ZrO2-3%molY2O3 sol-gel coating.",
        "The samples were tested in 60 wt.% NaNO3/40 wt.% KNO3 at 500 °C after 24 h and 2000 h.",
        "Table 2. Values of each equivalent circuit element with the protective layer model.",
        TABLE_HEADER,
        ROW_24,
        ROW_2000,
        "Figure 3. Impedance spectra of coated P91 samples; curves only, without numeric coordinates.",
    ))
    return SourceBundle(
        source=SourceMetadata(source_id="src-eis", filename="eis.pdf", source_checksum="abc"),
        pages=[SourcePageContext(
            page=6,
            native_text=text,
            text=text,
            native_parser="pymupdf",
            parser="pymupdf",
            origin="native_text",
            sufficient=True,
        )],
        tables=[],
    )


def _evidence(snippet: str) -> list[dict]:
    return [{
        "page": 6,
        "text_snippet": snippet,
        "source_type": "text",
        "original_source_type": "native_text",
    }]


def _document() -> CorrosionDocument:
    return CorrosionDocument.model_validate({
        "source": {"title": "EIS fixture", "doi": "10.3390/ma16020546"},
        "paper_types": ["coating_surface_treatment", "impedance_eis"],
        "materials": [{
            "local_id": "p91",
            "reported_name": "9Cr-1Mo P91 steel",
            "material_class": "alloy",
            "role": "working_electrode",
            "ownership": "focal_work",
            "evidence": _evidence("9Cr-1Mo P91 steel"),
        }],
        "treatments": [{
            "treatment_id": "ysz",
            "treatment_type": "coating",
            "reported_name": "ZrO2-3%molY2O3 sol-gel coating",
            "material_ref": "p91",
            "ownership": "focal_work",
            "evidence": _evidence("ZrO2-3%molY2O3 sol-gel coating"),
        }],
        "environments": [
            {
                "environment_id": "salt-24",
                "electrolyte": "60 wt.% NaNO3/40 wt.% KNO3",
                "temperature": {"raw_value": "500 °C", "value": 500, "unit": "°C"},
                "exposure_time": {"raw_value": "24 h", "value": 24, "unit": "h"},
                "evidence": _evidence(
                    "The samples were tested in 60 wt.% NaNO3/40 wt.% KNO3 at 500 °C after 24 h and 2000 h."
                ),
            },
            {
                "environment_id": "salt-2000",
                "electrolyte": "60 wt.% NaNO3/40 wt.% KNO3",
                "temperature": {"raw_value": "500 °C", "value": 500, "unit": "°C"},
                "exposure_time": {"raw_value": "2000 h", "value": 2000, "unit": "h"},
                "evidence": _evidence(
                    "The samples were tested in 60 wt.% NaNO3/40 wt.% KNO3 at 500 °C after 24 h and 2000 h."
                ),
            },
        ],
        "experiments": [
            {
                "experiment_id": "eis-24",
                "experiment_type": "eis",
                "material_refs": ["p91"],
                "treatment_refs": ["ysz"],
                "environment_ref": "salt-24",
                "eis_conditions": {},
                "ownership": "focal_work",
            },
            {
                "experiment_id": "eis-2000",
                "experiment_type": "eis",
                "material_refs": ["p91"],
                "treatment_refs": ["ysz"],
                "environment_ref": "salt-2000",
                "eis_conditions": {},
                "ownership": "focal_work",
            },
        ],
    })


def _archive():
    bundle = _bundle()
    recovered = recover_corrosion_parameter_tables(_document(), bundle)
    verified = verify_corrosion_document_evidence(recovered, bundle)
    return recovered, verified, assemble_corrosion_archive(verified, source_bundle=bundle)


def test_native_eis_table_recovery_preserves_element_identity_and_cell_locator():
    recovered, verified, archive = _archive()
    first = recovered.experiments[0]
    assert first.eis_conditions.equivalent_circuit == "protective layer model"
    assert len(first.metrics) == 7
    by_term = {metric.reported_term: metric for metric in first.metrics}
    assert by_term["Re"].property == "solution_resistance"
    assert by_term["Rt"].property == "charge_transfer_resistance"
    assert by_term["Rcp"].property == "protective_layer_resistance"
    assert by_term["Cdl"].property == "cpe_parameter"
    assert by_term["Cdl"].element_role == "double_layer"
    assert by_term["Ccp"].element_role == "protective_layer"
    assert by_term["ndl"].property == "cpe_exponent"
    assert by_term["ncp"].property == "cpe_exponent"
    assert by_term["Re"].evidence[0].locator == "Table 2:p6:r1:c1"
    assert by_term["Re"].evidence[1].text_snippet == ROW_24
    assert by_term["Re"].evidence[2].text_snippet == TABLE_HEADER
    assert all(metric.data_kind == "fitted_parameter" for metric in first.metrics)
    assert all(metric.evidence[0].verbatim_match is True for metric in verified.experiments[0].metrics)
    assert all(not experiment.eis_spectrum_points for experiment in recovered.experiments)
    assert sum(len(experiment.outputs) for experiment in archive.experiments) == 14


def test_locked_eis_fixture_recovers_all_six_table_rows_without_figure_digitization():
    case = load_live_case("CORR-EIS-D", REPO_ROOT)
    bundle = build_source_bundle(
        case.pdf_path,
        source_filename=case.filename,
        enable_ocr=False,
        include_figures=False,
    )
    exposure_times = (24, 72, 500, 1000, 1500, 2000)
    document = CorrosionDocument.model_validate({
        "source": {"title": case.title, "doi": case.doi},
        "materials": [{"local_id": "p91", "reported_name": "P91"}],
        "environments": [{
            "environment_id": f"salt-{hours}",
            "exposure_time": {"raw_value": f"{hours} h", "value": hours, "unit": "h"},
        } for hours in exposure_times],
        "experiments": [{
            "experiment_id": f"eis-{hours}",
            "experiment_type": "eis",
            "material_refs": ["p91"],
            "environment_ref": f"salt-{hours}",
            "eis_conditions": {},
        } for hours in exposure_times],
    })
    recovered = recover_corrosion_parameter_tables(document, bundle)
    assert [len(experiment.metrics) for experiment in recovered.experiments] == [7] * 6
    assert sum(len(experiment.metrics) for experiment in recovered.experiments) == 42
    assert all(not experiment.eis_spectrum_points for experiment in recovered.experiments)
    assert recovered.experiments[0].metrics[0].quantity.value == 7.557
    assert recovered.experiments[-1].metrics[-1].quantity.value == 0.610
    assert recovered.experiments[0].metrics[0].evidence[0].page == 6


def test_eis_gold_scores_value_type_condition_and_source_tracking():
    _, _, archive = _archive()
    gold = json.loads((REPO_ROOT / "benchmark/corrosion_v1/gold/CORR-EIS-D.json").read_text(encoding="utf-8"))
    expected = expectations_from_gold(gold)
    assert gold["benchmark_safeguards"]["raw_spectrum_points_expected"] == 0
    assert gold["benchmark_safeguards"]["protective_layer_resistance_must_not_be_relabelled_as_charge_transfer_resistance"] is True
    score = score_corrosion_archive(archive, expected)
    assert len(expected) == 14
    assert score.matched_required == 14
    assert score.value_accuracy == 1.0
    assert score.scientific_type_accuracy == 1.0
    assert score.association_accuracy == 1.0
    assert score.source_tracking_coverage == 1.0
    assert score.overall == 1.0


def test_fitted_metrics_project_for_exposure_analytics_without_raw_spectrum_invention():
    _, _, archive = _archive()
    rows = project_archives([archive])
    rt_rows = [row for row in rows if row.property_name == "charge_transfer_resistance"]
    assert {row.conditions["exposure_time"] for row in rt_rows} == {24.0, 2000.0}
    assert all(row.conditions["data_kind"] == "fitted_parameter" for row in rt_rows)
    assert all(row.conditions["equivalent_circuit"] == "protective layer model" for row in rt_rows)
    assert not any(row.conditions.get("data_kind") == "raw_spectrum" for row in rows)


def test_rp_rct_and_protective_layer_resistance_remain_distinct():
    evidence = [CorrosionEvidence(
        page=1,
        text_snippet="value 10 Ω",
        source_type="text",
        original_source_type="native_text",
        verbatim_match=True,
    )]

    def metric(property_name: str) -> CorrosionMetric:
        return CorrosionMetric(
            property=property_name,
            reported_term={
                "polarization_resistance": "Rp",
                "charge_transfer_resistance": "Rct",
                "protective_layer_resistance": "Rcp",
            }[property_name],
            quantity=CorrosionQuantity(raw_value="10 Ω", value=10, unit="Ω"),
            data_kind="fitted_parameter",
            ownership="focal_work",
            evidence=evidence,
        )

    common = dict(
        scope_status="supported",
        experiment_type="eis",
        reference_electrode=None,
        treatment_present=True,
        unresolved_conflict=False,
        equivalent_circuit="protective layer model",
    )
    rp = decide_corrosion_metric_admission(metric("polarization_resistance"), **common)
    rct = decide_corrosion_metric_admission(metric("charge_transfer_resistance"), **common)
    rcp = decide_corrosion_metric_admission(metric("protective_layer_resistance"), **common)
    assert rp.admitted is False
    assert rp.reason == "polarization_resistance_misclassified_as_eis"
    assert rct.admitted is True
    assert rcp.admitted is True


def test_fitted_parameter_requires_reported_equivalent_circuit_context():
    metric = CorrosionMetric(
        property="charge_transfer_resistance",
        reported_term="Rt",
        quantity=CorrosionQuantity(raw_value="13.87 Ω", value=13.87, unit="Ω"),
        data_kind="fitted_parameter",
        ownership="focal_work",
        evidence=[CorrosionEvidence(
            page=6,
            text_snippet="13.87",
            source_type="table",
            original_source_type="native_text",
            verbatim_match=True,
        )],
    )
    decision = decide_corrosion_metric_admission(
        metric,
        scope_status="supported",
        experiment_type="eis",
        reference_electrode=None,
        treatment_present=True,
        unresolved_conflict=False,
        equivalent_circuit=None,
    )
    assert decision.admitted is False
    assert decision.reason == "missing_equivalent_circuit_context"


def test_explicit_raw_spectrum_points_keep_frequency_pairing_and_origin():
    bundle = _bundle()
    verified = verify_corrosion_document_evidence(
        recover_corrosion_parameter_tables(_document(), bundle), bundle
    )
    payload = verified.model_dump(mode="python")
    payload["experiments"][0]["eis_spectrum_points"] = [{
        "point_id": "nyquist-1",
        "frequency": {"raw_value": "1000 Hz", "value": 1000, "unit": "Hz"},
        "impedance_real": {"raw_value": "2 Ω", "value": 2, "unit": "Ω"},
        "negative_impedance_imaginary": {"raw_value": "3 Ω", "value": 3, "unit": "Ω"},
        "source_origin": "table_reported",
        "evidence": [{
            "source_id": "src-eis",
            "page": 6,
            "text_snippet": "1000 2 3",
            "source_type": "table",
            "original_source_type": "table_reported",
            "table_id": "Table S1",
            "locator": "Table S1:r1",
            "verbatim_match": True,
        }],
    }]
    archive = assemble_corrosion_archive(CorrosionDocument.model_validate(payload), source_bundle=bundle)
    spectrum_rows = [
        row for row in project_archives([archive])
        if row.conditions.get("data_kind") == "raw_spectrum"
    ]
    assert {row.property_name for row in spectrum_rows} == {
        "impedance_real", "negative_impedance_imaginary"
    }
    assert all(row.conditions["frequency"] == 1000 for row in spectrum_rows)
    assert all(row.conditions["frequency_unit"] == "Hz" for row in spectrum_rows)
    assert all(row.conditions["source_origin"] == "table_reported" for row in spectrum_rows)


def test_eis_quarantine_retains_rp_and_cited_rate_without_canonical_contamination():
    bundle = _bundle()
    verified = verify_corrosion_document_evidence(
        recover_corrosion_parameter_tables(_document(), bundle), bundle
    )
    payload = verified.model_dump(mode="python")
    exact = {
        "source_id": "src-eis",
        "page": 6,
        "text_snippet": ROW_24,
        "source_type": "table",
        "original_source_type": "native_text",
        "table_id": "Table 2",
        "locator": "Table 2:p6:r1",
        "verbatim_match": True,
    }
    payload["experiments"][0]["metrics"].extend((
        {
            "property": "polarization_resistance",
            "reported_term": "Rp",
            "quantity": {"raw_value": "10 Ω", "value": 10, "unit": "Ω"},
            "data_kind": "fitted_parameter",
            "ownership": "focal_work",
            "evidence": [exact],
        },
        {
            "property": "corrosion_rate",
            "quantity": {"raw_value": "118 µm year^-1", "value": 118, "unit": "µm year^-1"},
            "data_kind": "derived_metric",
            "ownership": "cited_prior_work",
            "evidence": [exact],
        },
    ))
    archive = assemble_corrosion_archive(CorrosionDocument.model_validate(payload), source_bundle=bundle)
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    reasons = {item["reason"] for item in audit["quarantine"]}
    assert "polarization_resistance_misclassified_as_eis" in reasons
    assert "ownership_cited_prior_work" in reasons
    canonical_properties = {
        output.property for experiment in archive.experiments for output in experiment.outputs
    }
    assert "polarization_resistance" not in canonical_properties
    assert "corrosion_rate" not in canonical_properties


def test_scientific_unicode_normalization_is_typographic_not_conceptual():
    assert normalize_scientific_text("500 ◦C") == normalize_scientific_text("500 °C")
    assert normalize_scientific_text("22.62 µm·year−1") == normalize_scientific_text(
        "22.62 μm∙year-1"
    )
    assert normalize_scientific_text("10 Ω") == normalize_scientific_text("10 Ω")
    assert normalize_scientific_text("1\u202f000") == normalize_scientific_text("1 000")
    assert normalize_scientific_text("Rct") != normalize_scientific_text("Rp")
    assert normalize_scientific_text("CPE Q") != normalize_scientific_text("capacitance")
    assert normalize_scientific_text("SCE") != normalize_scientific_text("Ag/AgCl")


def test_author_estimated_focal_rate_verifies_without_rewriting_raw_source_text():
    bundle = _bundle()
    source_sentence = (
        "Firstly, the corrosion rate of 22.62 μm∙year−1 of the coated steel, "
        "estimated after 2000 h of testing, falls well below prior work."
    )
    bundle.pages.append(SourcePageContext(
        page=9,
        native_text=source_sentence,
        text=source_sentence,
        native_parser="pymupdf",
        parser="pymupdf",
        origin="native_text",
        sufficient=True,
    ))
    recovered = recover_corrosion_parameter_tables(_document(), bundle)
    recovered.experiments[-1].metrics.append(CorrosionMetric(
        property="corrosion_rate",
        reported_term="corrosion rate",
        quantity=CorrosionQuantity(
            raw_value="22.62 µm·year−1",
            value=22.62,
            unit="µm/year",
        ),
        method="EIS",
        data_kind="derived_metric",
        ownership="focal_work",
        evidence=[CorrosionEvidence(
            page=9,
            section="Corrosion Rate Estimation",
            text_snippet=(
                "the corrosion rate of 22.62 µm·year−1 of the coated steel, "
                "estimated after 2000 h of testing"
            ),
            source_type="text",
            original_source_type="native_text",
        )],
    ))

    verified = verify_corrosion_document_evidence(recovered, bundle)
    metric = verified.experiments[-1].metrics[-1]
    assert metric.evidence[0].verbatim_match is True
    assert metric.quantity.raw_value == "22.62 µm·year−1"
    assert metric.evidence[0].text_snippet.endswith("estimated after 2000 h of testing")
    assert bundle.pages[-1].native_text == source_sentence

    archive = assemble_corrosion_archive(verified, source_bundle=bundle)
    admitted = [
        output
        for experiment in archive.experiments
        for output in experiment.outputs
        if output.property == "corrosion_rate"
    ]
    assert len(admitted) == 1
    assert admitted[0].conditions["data_kind"] == "derived_metric"
