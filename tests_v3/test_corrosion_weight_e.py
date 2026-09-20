from __future__ import annotations

import json
from pathlib import Path
import shutil

from synthex_platform.benchmarks.corrosion import score_corrosion_archive
from synthex_platform.benchmarks.corrosion_live import (
    expectations_from_gold,
    load_live_case,
    quarantine_expectations_from_gold,
    replay_saved_live_corrosion_case,
)
from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_admission import decide_corrosion_metric_admission
from synthex_platform.extraction.corrosion_evidence import verify_corrosion_document_evidence
from synthex_platform.extraction.corrosion_gravimetric_recovery import recover_corrosion_gravimetric_candidates
from synthex_platform.extraction.corrosion_models import (
    CorrosionDocument,
    CorrosionEvidence,
    CorrosionMetric,
    CorrosionQuantity,
)
from synthex_platform.extraction.corrosion_units import (
    corrosion_metric_unit_is_compatible,
    corrosion_unit_category,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import SourceBundle, SourceMetadata, SourcePageContext
from synthex_platform.visual.analytics.projection import project_archives


REPO_ROOT = Path(__file__).parents[1]
METHOD = (
    "Mild steel samples were immersed in 1.0 M HCl for 1, 5, 10 and 24 h in triplicate, "
    "and every sample was weighed three times."
)
CR_SENTENCE = (
    "ETO exhibits an increase in corrosion rate with increasing temperature: 1.15 mm/y at 303 K, "
    "1.62 mm/y at 313 K, 1.15 mm/y at 323 K, and 1.82 mm/y at 333 K at an inhibitor "
    "concentration of 500 ppm and immersion time of 5 h (Fig. 3)."
)
IE_SENTENCE = (
    "On the other hand, the inhibition efficiency at the same concentrations and immersion time "
    "was 98.4% at 303 K, 92.0% at 313 K, 84.8% at 323 K, and 80.1% at 333 K at the inhibitor "
    "concentration of 500 ppm and immersion time of 5 h."
)
AMBIGUOUS_SENTENCE = (
    "For instance, the inhibition efficiencies of 100, 200, 300, 400, 500 and 600 ppm ETO are "
    "52.6, 77.3, 81.5, 95.2, 98.4 and 98.6% and the corrosion rates are 2.71, 1.74, 1.28, "
    "1.17, 0.97, and 0.94 mm/year, respectively."
)
CITED_ROW = "N'-(2-(2-oxomethylpyrrol-1-yl)ethyl)piperidine MS HCl 91.9 28"


def _evidence(snippet: str, page: int = 3) -> list[dict]:
    return [{"page": page, "text_snippet": snippet, "source_type": "text"}]


def _bundle() -> SourceBundle:
    page_2 = METHOD
    page_3 = "\n".join((
        "3.2. Weight-Loss studies",
        "mild steel",
        "1.0 M HCl",
        CR_SENTENCE,
        IE_SENTENCE,
        AMBIGUOUS_SENTENCE,
        "Fig. 3. Corrosion rate and inhibition efficiency for ETO at various temperatures.",
    ))
    page_5 = "\n".join(("Table 2. Comparison of reported corrosion inhibitors.", CITED_ROW))
    return SourceBundle(
        source=SourceMetadata(
            source_id="src-weight-e",
            filename="Corrosion 5.pdf",
            source_checksum="weight-e-checksum",
        ),
        pages=[
            SourcePageContext(
                page=2, native_text=page_2, text=page_2, native_parser="pymupdf",
                parser="pymupdf", origin="native_text", sufficient=True,
            ),
            SourcePageContext(
                page=3, native_text=page_3, text=page_3, native_parser="pymupdf",
                parser="pymupdf", origin="native_text", sufficient=True,
            ),
            SourcePageContext(
                page=5, native_text=page_5, text=page_5, native_parser="pymupdf",
                parser="pymupdf", origin="native_text", sufficient=True,
            ),
        ],
    )


def _document() -> CorrosionDocument:
    return CorrosionDocument.model_validate({
        "source": {"title": "ETO mild-steel inhibitor study", "doi": "10.1016/j.sajce.2022.06.011"},
        "paper_types": ["inhibitor_study", "immersion_weight_loss"],
        "materials": [{
            "local_id": "mild-steel",
            "reported_name": "mild steel",
            "material_class": "alloy",
            "role": "corroding_material",
            "ownership": "focal_work",
            "evidence": _evidence("mild steel"),
        }],
        "treatments": [{
            "treatment_id": "eto-500",
            "treatment_type": "inhibitor",
            "reported_name": "ETO",
            "material_ref": "mild-steel",
            "concentration": {"raw_value": "500 ppm", "value": 500, "unit": "ppm", "qualifier": "exact"},
            "ownership": "focal_work",
            "evidence": _evidence(CR_SENTENCE),
        }],
        "environments": [
            {
                "environment_id": "hcl-303-5h",
                "medium": "1.0 M HCl",
                "electrolyte": "1.0 M HCl",
                "temperature": {"raw_value": "303 K", "value": 303, "unit": "K", "qualifier": "exact"},
                "exposure_time": {"raw_value": "5 h", "value": 5, "unit": "h", "qualifier": "exact"},
                "inhibitor_ref": "eto-500",
                "evidence": [*_evidence("1.0 M HCl"), *_evidence(CR_SENTENCE)],
            },
            {
                "environment_id": "hcl-ambiguous-time",
                "medium": "1.0 M HCl",
                "electrolyte": "1.0 M HCl",
                "inhibitor_ref": "eto-500",
                "evidence": _evidence("1.0 M HCl"),
            },
        ],
        "experiments": [
            {
                "experiment_id": "weight-303-5h",
                "experiment_type": "weight_loss",
                "material_refs": ["mild-steel"],
                "environment_ref": "hcl-303-5h",
                "treatment_refs": ["eto-500"],
                "gravimetric_conditions": {
                    "specimen_dimensions": "2.0 cm x 0.05 cm x 1.0 cm",
                    "replicate_count": 3,
                    "weighing_repetitions": 3,
                    "evidence": _evidence(METHOD, page=2),
                },
                "metrics": [
                    {
                        "property": "corrosion_rate",
                        "reported_term": "corrosion rate",
                        "quantity": {"raw_value": "1.15 mm/y", "value": 1.15, "unit": "mm/y", "qualifier": "exact"},
                        "method": "weight loss",
                        "data_kind": "derived_metric",
                        "ownership": "focal_work",
                        "evidence": _evidence(CR_SENTENCE),
                    },
                    {
                        "property": "inhibition_efficiency",
                        "reported_term": "inhibition efficiency",
                        "quantity": {"raw_value": "98.4%", "value": 98.4, "unit": "%", "qualifier": "exact"},
                        "method": "weight loss",
                        "data_kind": "derived_metric",
                        "ownership": "focal_work",
                        "evidence": _evidence(f"{CR_SENTENCE}\n{IE_SENTENCE}"),
                    },
                ],
                "ownership": "focal_work",
                "evidence": _evidence(CR_SENTENCE),
            },
            {
                "experiment_id": "weight-ambiguous-time",
                "experiment_type": "weight_loss",
                "material_refs": ["mild-steel"],
                "environment_ref": "hcl-ambiguous-time",
                "treatment_refs": ["eto-500"],
                "metrics": [{
                    "property": "corrosion_rate",
                    "reported_term": "corrosion rate",
                    "quantity": {"raw_value": "0.97 mm/year", "value": 0.97, "unit": "mm/year"},
                    "data_kind": "derived_metric",
                    "ownership": "focal_work",
                    "evidence": _evidence(AMBIGUOUS_SENTENCE),
                }],
                "ownership": "focal_work",
                "evidence": _evidence(AMBIGUOUS_SENTENCE),
            },
            {
                "experiment_id": "comparison-table-row",
                "experiment_type": "weight_loss",
                "material_refs": ["mild-steel"],
                "environment_ref": "hcl-ambiguous-time",
                "metrics": [{
                    "property": "inhibition_efficiency",
                    "reported_term": "IE",
                    "quantity": {"raw_value": "91.9", "value": 91.9, "unit": "%"},
                    "data_kind": "derived_metric",
                    "ownership": "cited_prior_work",
                    "evidence": _evidence(CITED_ROW, page=5),
                }],
                "ownership": "focal_work",
                "evidence": _evidence(CITED_ROW, page=5),
            },
        ],
    })


def _archive():
    bundle = _bundle()
    verified = verify_corrosion_document_evidence(_document(), bundle)
    return verified, assemble_corrosion_archive(verified, source_bundle=bundle)


def test_corr_weight_e_locked_case_and_routing_contract_are_present():
    case = load_live_case("CORR-WEIGHT-E", REPO_ROOT)
    assert case.pdf_path.exists()
    assert case.expected_domain == "corrosion"
    route = DomainRouter().route_text(
        "Weight-loss corrosion experiments immersed mild steel coupons in 1.0 M HCl. "
        "Mass loss, corrosion rate, inhibition efficiency, exposure time and inhibitor "
        "concentration were reported for the focal specimens."
    )
    assert route.domain == "corrosion"
    assert "immersion_weight_loss" in route.paper_types


def test_gravimetric_unit_categories_never_equate_mass_loss_and_penetration_rates():
    assert corrosion_unit_category("mg cm^-2 h^-1") == "mass_loss_rate"
    assert corrosion_unit_category("g m^-2 day^-1") == "mass_loss_rate"
    assert corrosion_unit_category("mm/year") == "penetration_rate"
    assert corrosion_unit_category("µm/year") == "penetration_rate"
    assert corrosion_unit_category("mpy") == "penetration_rate"
    assert corrosion_metric_unit_is_compatible("corrosion_rate", "mg cm^-2 h^-1")
    assert corrosion_metric_unit_is_compatible("penetration_rate", "mm/year")
    assert not corrosion_metric_unit_is_compatible("penetration_rate", "mg cm^-2 h^-1")
    assert not corrosion_metric_unit_is_compatible("mass_loss", "mm/year")


def test_weight_loss_admission_preserves_measured_vs_author_derived_classification():
    evidence = [CorrosionEvidence(
        page=2,
        text_snippet="The measured mass loss was 12.5 mg after 5 h in 1.0 M HCl.",
        source_type="text",
        original_source_type="native_text",
        verbatim_match=True,
    )]
    common = {
        "scope_status": "supported",
        "experiment_type": "weight_loss",
        "reference_electrode": None,
        "treatment_present": False,
        "unresolved_conflict": False,
        "condition_properties": {"medium", "exposure_time"},
    }
    measured = CorrosionMetric(
        property="mass_loss",
        quantity=CorrosionQuantity(raw_value="12.5 mg", value=12.5, unit="mg"),
        data_kind="reported_measurement",
        ownership="focal_work",
        evidence=evidence,
    )
    mislabelled = measured.model_copy(update={"data_kind": "derived_metric"})
    assert decide_corrosion_metric_admission(measured, **common).admitted is True
    assert decide_corrosion_metric_admission(mislabelled, **common).reason == "invalid_gravimetric_data_kind"

    author_rate = measured.model_copy(update={
        "property": "corrosion_rate",
        "quantity": CorrosionQuantity(raw_value="1.15 mm/y", value=1.15, unit="mm/y"),
        "data_kind": "derived_metric",
    })
    wrong_rate_kind = author_rate.model_copy(update={"data_kind": "reported_measurement"})
    assert decide_corrosion_metric_admission(author_rate, **common).admitted is True
    assert decide_corrosion_metric_admission(wrong_rate_kind, **common).reason == "invalid_gravimetric_data_kind"


def test_weight_loss_gold_scores_value_type_association_source_and_quarantine():
    verified, archive = _archive()
    gold = json.loads(
        (REPO_ROOT / "benchmark/corrosion_v1/gold/CORR-WEIGHT-E.json").read_text(encoding="utf-8")
    )
    expected = expectations_from_gold(gold)
    exclusions = quarantine_expectations_from_gold(gold)
    score = score_corrosion_archive(archive, expected, exclusions)

    assert len(expected) == 2
    assert len(exclusions) == 2
    assert score.matched_required == score.total_required == 2
    assert score.value_accuracy == 1.0
    assert score.scientific_type_accuracy == 1.0
    assert score.association_accuracy == 1.0
    assert score.source_tracking_coverage == 1.0
    assert score.quarantine_matches == score.quarantine_total == 2
    assert score.quarantine_correctness == 1.0
    assert score.overall == 1.0
    assert verified.experiments[0].gravimetric_conditions.exposed_area is None


def test_weight_loss_archive_keeps_only_two_source_reported_derived_metrics():
    _, archive = _archive()
    outputs = [output for experiment in archive.experiments for output in experiment.outputs]
    assert [(item.property, item.value) for item in outputs] == [
        ("corrosion_rate", 1.15),
        ("inhibition_efficiency", 98.4),
    ]
    assert all(item.conditions["data_kind"] == "derived_metric" for item in outputs)
    assert not any(item.property in {"initial_mass", "final_mass", "mass_loss"} for item in outputs)

    audit = archive.domain_payloads[0].values["admissibility_audit"]
    reasons = {entry["object"].get("quantity", {}).get("value"): entry["reason"] for entry in audit["quarantine"]}
    assert reasons[0.97] == "no_verified_value_specific_evidence"
    assert reasons[91.9] == "ownership_cited_prior_work"


def test_weight_loss_projection_uses_actual_joint_rows_without_grid_generation():
    _, archive = _archive()
    rows = project_archives([archive])
    assert len(rows) == 2
    assert {row.property_name for row in rows} == {"corrosion_rate", "inhibition_efficiency"}
    for row in rows:
        assert row.conditions["temperature"] == 303
        assert row.conditions["exposure_time"] == 5
        assert row.conditions["inhibitor_concentration"] == 500
        assert row.conditions["replicate_count"] == 3
        assert row.conditions["weighing_repetitions"] == 3


def test_figure_caption_alone_cannot_ground_a_weight_loss_value():
    payload = _document().model_dump(mode="python")
    payload["experiments"][0]["metrics"][0]["evidence"] = [{
        "page": 3,
        "text_snippet": "Fig. 3. Corrosion rate and inhibition efficiency for ETO at various temperatures.",
        "source_type": "figure_caption",
    }]
    verified = verify_corrosion_document_evidence(CorrosionDocument.model_validate(payload), _bundle())
    assert verified.experiments[0].metrics[0].evidence[0].verbatim_match is False


def test_ambiguous_sweep_recovery_preserves_distinct_condition_candidates():
    bundle = _bundle()
    recovered = recover_corrosion_gravimetric_candidates(_document(), bundle)
    candidate = next(
        item for item in recovered.experiments
        if item.experiment_id == "recovered_weight_ambiguous_eto_100ppm"
    )
    values = {(item.property, item.quantity.value) for item in candidate.metrics}
    assert values == {("corrosion_rate", 2.71), ("inhibition_efficiency", 52.6)}
    environment = next(item for item in recovered.environments if item.environment_id == candidate.environment_ref)
    assert environment.exposure_time is None
    verified = verify_corrosion_document_evidence(recovered, bundle)
    verified_candidate = next(
        item for item in verified.experiments if item.experiment_id == candidate.experiment_id
    )
    assert all(item.evidence[0].text_snippet in bundle.pages[1].native_text for item in verified_candidate.metrics)
    assert all(item.evidence[0].verbatim_match is False for item in verified_candidate.metrics)
    archive = assemble_corrosion_archive(verified, source_bundle=bundle)
    assert not any(
        output.value in {2.71, 52.6}
        for experiment in archive.experiments
        for output in experiment.outputs
    )


def test_saved_provider_payload_replay_is_offline_and_keeps_raw_score_separate(tmp_path):
    benchmark = tmp_path / "benchmark" / "corrosion_v1"
    output = tmp_path / "output" / "corrosion_v1" / "live" / "CORR-WEIGHT-E"
    (benchmark / "corpus pdfs").mkdir(parents=True)
    (benchmark / "gold").mkdir()
    output.mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "benchmark/corrosion_v1/corpus pdfs/Corrosion 5.pdf",
        benchmark / "corpus pdfs/Corrosion 5.pdf",
    )
    shutil.copy2(
        REPO_ROOT / "benchmark/corrosion_v1/gold/CORR-WEIGHT-E.json",
        benchmark / "gold/CORR-WEIGHT-E.json",
    )
    (benchmark / "corpus_manifest.json").write_text(json.dumps({"entries": [{
        "id": "CORR-WEIGHT-E", "role": "gold", "filename": "Corrosion 5.pdf",
        "expected_title": "ETO mild-steel inhibitor study",
        "expected_doi": "10.1016/j.sajce.2022.06.011",
    }]}), encoding="utf-8")
    seed = CorrosionDocument.model_validate({
        "source": {"title": "ETO mild-steel inhibitor study", "doi": "10.1016/j.sajce.2022.06.011"},
        "paper_types": ["inhibitor_study", "immersion_weight_loss", "computational_corrosion"],
        "materials": [{
            "local_id": "mild_steel", "reported_name": "mild steel",
            "material_class": "alloy", "role": "corroding_material", "ownership": "focal_work",
            "evidence": [{"page": 2, "text_snippet": "mild steel", "source_type": "text"}],
        }],
    })
    document_path = output / "verified_document.json"
    report_path = output / "report.json"
    document_path.write_text(seed.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(json.dumps({"score": {
        "matched_required": 0, "total_required": 2, "overall": 0.0,
    }}), encoding="utf-8")
    before = (document_path.read_bytes(), report_path.read_bytes())

    replay = replay_saved_live_corrosion_case("CORR-WEIGHT-E", tmp_path)

    assert replay["provider_calls"] == 0
    assert replay["historical_artifacts_mutated"] is False
    assert replay["raw_provider_score"]["overall"] == 0.0
    assert replay["post_recovery_score"]["matched_required"] == 2
    assert replay["post_recovery_score"]["quarantine_matches"] == 2
    assert replay["post_recovery_score"]["overall"] == 1.0
    assert before == (document_path.read_bytes(), report_path.read_bytes())
