from __future__ import annotations

from synthex_platform.extraction.catalysis_assembler import assemble_catalysis_archive
from synthex_platform.extraction.catalysis_extractor import CATALYSIS_RULES
from synthex_platform.extraction.catalysis_models import CatalysisDocument
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import build_visualization_spec, chart_field_options


def _ev(text: str) -> dict:
    return {
        "page": 1,
        "source_type": "text",
        "original_source_type": "native_text",
        "text_snippet": text,
    }


def _q(raw: str, value: float, unit: str | None = None) -> dict:
    return {
        "raw_value": raw,
        "value": value,
        "unit": unit,
        "qualifier": "exact",
    }


def _document(*, include_prediction: bool = False, four_run_surface: bool = False) -> tuple[CatalysisDocument, str]:
    source_lines = [
        "MgO photocatalyst was used in the photocatalytic degradation experiments.",
    ]
    run_specs = [
        ("run-1", 5.0, 0.5, 80.0),
    ]
    if four_run_surface:
        run_specs = [
            ("run-1", 5.0, 0.5, 80.0),
            ("run-2", 5.0, 1.0, 86.0),
            ("run-3", 7.0, 0.5, 89.0),
            ("run-4", 7.0, 1.0, 94.0),
        ]

    experiments = []
    for run_id, ph, dose, observed in run_specs:
        ph_text = f"{run_id}: pH = {ph:g}."
        dose_text = f"{run_id}: catalyst dose = {dose:g} g/L."
        concentration_text = f"{run_id}: initial concentration = 20 mg/L."
        time_text = f"{run_id}: irradiation time = 60 min."
        observed_text = f"{run_id}: observed degradation efficiency = {observed:g}%."
        source_lines.extend([ph_text, dose_text, concentration_text, time_text, observed_text])
        metrics = [{
            "property": "degradation_efficiency",
            "raw_value": f"{observed:g}%",
            "value": observed,
            "unit": "%",
            "qualifier": "exact",
            "reactant": "model dye",
            "response_origin": "observed",
            "ownership": "focal_work",
            "evidence": [_ev(observed_text)],
        }]
        if include_prediction and run_id == "run-1":
            predicted_text = "run-1: RSM predicted degradation efficiency = 78%."
            source_lines.append(predicted_text)
            metrics.append({
                "property": "degradation_efficiency",
                "raw_value": "78%",
                "value": 78.0,
                "unit": "%",
                "qualifier": "exact",
                "reactant": "model dye",
                "response_origin": "model_predicted",
                "model_name": "response surface methodology",
                "ownership": "focal_work",
                "evidence": [_ev(predicted_text)],
            })
        experiments.append({
            "experiment_id": run_id,
            "catalyst_ref": "cat-mgo",
            "reaction": {
                "reported_reaction": "photocatalytic degradation of model dye",
                "reaction_class": "photocatalysis",
                "reactants": [{"reported_name": "model dye"}],
            },
            "experimental_conditions": {
                "pH": _q(f"{ph:g}", ph),
                "catalyst_dose": _q(f"{dose:g} g/L", dose, "g/L"),
                "initial_concentration": _q("20 mg/L", 20.0, "mg/L"),
                "irradiation_time": _q("60 min", 60.0, "min"),
            },
            "metrics": metrics,
            "ownership": "focal_work",
            "evidence": [
                _ev(ph_text),
                _ev(dose_text),
                _ev(concentration_text),
                _ev(time_text),
            ],
        })

    doc = CatalysisDocument.model_validate({
        "source": {
            "title": "Photocatalytic degradation of model dye using MgO and response surface methodology",
        },
        "paper_types": ["heterogeneous_catalysis", "catalyst_dataset_modelling"],
        "scope_status": "deferred_subtype",
        "catalysts": [{
            "local_id": "cat-mgo",
            "reported_name": "MgO",
            "formula": "MgO",
            "state": "as_synthesized",
            "ownership": "focal_work",
            "evidence": [_ev(source_lines[0])],
        }],
        "heterogeneous_experiments": experiments,
    })
    source_text = "--- PAGE 1 ---\n" + "\n".join(source_lines)
    return doc, source_text


def test_prompt_explicitly_supports_photocatalysis_rsm_matrices():
    assert "photocatalysis and photocatalytic" in CATALYSIS_RULES
    assert "experimental_conditions" in CATALYSIS_RULES
    assert "response_origin=model_predicted" in CATALYSIS_RULES
    assert "extract EVERY explicit run" in CATALYSIS_RULES


def test_deferred_explicit_photocatalysis_is_narrowly_promoted_and_conditions_are_admitted():
    doc, source_text = _document()
    archive = assemble_catalysis_archive(doc, source_text=source_text)

    assert archive.domain_payloads[0].schema_version == "1.1-photocatalysis-rsm"
    validated = archive.domain_payloads[0].values["validated_document"]
    assert validated["scope_status"] == "supported"
    assert "photocatalysis_supported_v1_1" in archive.quality.semantic_warnings
    assert len(archive.materials) == 1
    assert len(archive.experiments) == 1

    experiment = archive.experiments[0]
    condition_map = {item.property: item for item in experiment.conditions}
    assert condition_map["pH"].value == 5.0
    assert condition_map["catalyst_dose"].value == 0.5
    assert condition_map["initial_concentration"].value == 20.0
    assert condition_map["irradiation_time"].value == 60.0
    assert all(item.evidence and item.evidence[0].verbatim_match is True for item in experiment.conditions)
    assert experiment.outputs[0].property == "degradation_efficiency"
    assert experiment.outputs[0].conditions["response_origin"] == "observed"


def test_observed_and_rsm_predicted_responses_stay_in_distinct_modalities():
    doc, source_text = _document(include_prediction=True)
    archive = assemble_catalysis_archive(doc, source_text=source_text)

    assert len(archive.experiments) == 1
    assert [item.value for item in archive.experiments[0].outputs] == [80.0]
    assert len(archive.calculations) == 1
    calculation = archive.calculations[0]
    assert calculation.calculation_type == "response_surface_model_prediction"
    assert calculation.method == "response surface methodology"
    assert [item.value for item in calculation.outputs] == [78.0]
    assert calculation.outputs[0].conditions["response_origin"] == "model_predicted"
    assert {item.property for item in calculation.parameters} >= {"pH", "catalyst_dose"}

    rows = project_archives([archive])
    assert {(row.modality, row.value) for row in rows if row.property_name == "degradation_efficiency"} == {
        ("experimental", 80.0),
        ("computational", 78.0),
    }


def test_rsm_surface_reaches_heatmap_and_contour_axes_without_cross_run_inference():
    doc, source_text = _document(four_run_surface=True)
    archive = assemble_catalysis_archive(doc, source_text=source_text)
    rows = [row for row in project_archives([archive]) if row.property_name == "degradation_efficiency"]

    assert len(rows) == 4
    assert {(row.conditions["pH"], row.conditions["catalyst_dose"]) for row in rows} == {
        (5.0, 0.5), (5.0, 1.0), (7.0, 0.5), (7.0, 1.0),
    }
    options = chart_field_options(rows, "heatmap")
    assert "conditions.pH" in options["x"]
    assert "conditions.catalyst_dose" in options["y"]

    heatmap = build_visualization_spec(
        rows,
        "heatmap",
        "Photocatalysis RSM surface",
        x_field="conditions.pH",
        y_field="conditions.catalyst_dose",
        z_field="value",
    )
    contour = build_visualization_spec(
        rows,
        "contour",
        "Photocatalysis RSM contour",
        x_field="conditions.pH",
        y_field="conditions.catalyst_dose",
        z_field="value",
    )
    assert heatmap.eligible
    assert contour.eligible


def test_unrelated_deferred_subtype_is_not_promoted():
    evidence_text = "Catalyst X gave 42% conversion during thermal testing."
    doc = CatalysisDocument.model_validate({
        "source": {"title": "Thermal catalyst study"},
        "paper_types": ["heterogeneous_catalysis"],
        "scope_status": "deferred_subtype",
        "catalysts": [{
            "local_id": "cat-x",
            "reported_name": "Catalyst X",
            "ownership": "focal_work",
            "evidence": [_ev(evidence_text)],
        }],
        "heterogeneous_experiments": [{
            "experiment_id": "thermal-1",
            "catalyst_ref": "cat-x",
            "reaction": {
                "reported_reaction": "thermal conversion of feed",
                "reaction_class": "other_heterogeneous",
            },
            "metrics": [{
                "property": "conversion",
                "raw_value": "42%",
                "value": 42,
                "unit": "%",
                "reactant": "feed",
                "ownership": "focal_work",
                "evidence": [_ev(evidence_text)],
            }],
            "ownership": "focal_work",
            "evidence": [_ev(evidence_text)],
        }],
    })
    source_text = "--- PAGE 1 ---\n" + evidence_text
    archive = assemble_catalysis_archive(doc, source_text=source_text)
    assert archive.domain_payloads[0].values["validated_document"]["scope_status"] == "deferred_subtype"
    assert not archive.materials
    assert not archive.experiments
