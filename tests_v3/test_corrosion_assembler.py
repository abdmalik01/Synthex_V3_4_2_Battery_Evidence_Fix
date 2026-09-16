from synthex_platform.extraction.corrosion_assembler import assemble_corrosion_archive
from synthex_platform.extraction.corrosion_models import CorrosionDocument


def _evidence(text: str = "The corrosion current density was 2.4 µA cm-2.") -> list[dict]:
    return [{
        "source_id": "src-local",
        "page": 3,
        "section": "Results",
        "text_snippet": text,
        "source_type": "text",
        "original_source_type": "native_text",
        "verbatim_match": True,
    }]


def _document() -> CorrosionDocument:
    ev = _evidence()
    return CorrosionDocument.model_validate({
        "source": {"title": "Corrosion test paper", "doi": "10.1000/corrosion"},
        "paper_types": ["polarization_corrosion", "computational_corrosion"],
        "materials": [{
            "local_id": "steel",
            "reported_name": "mild steel",
            "material_class": "alloy",
            "role": "corroding_material",
            "ownership": "focal_work",
            "evidence": ev,
        }],
        "treatments": [{
            "treatment_id": "inh",
            "treatment_type": "inhibitor",
            "reported_name": "organic inhibitor",
            "material_ref": "steel",
            "concentration": {"raw_value": "1×10^-3 M", "value": 0.001, "unit": "M", "qualifier": "exact"},
            "ownership": "focal_work",
            "evidence": ev,
        }],
        "environments": [{
            "environment_id": "acid",
            "medium": "1 M HCl",
            "electrolyte": "HCl",
            "temperature": {"raw_value": "298 K", "value": 298, "unit": "K", "qualifier": "exact"},
            "inhibitor_ref": "inh",
            "evidence": ev,
        }],
        "experiments": [{
            "experiment_id": "pol",
            "experiment_type": "potentiodynamic_polarization",
            "material_refs": ["steel"],
            "environment_ref": "acid",
            "treatment_refs": ["inh"],
            "polarization_conditions": {
                "reference_electrode": "Ag/AgCl",
                "scan_rate": {"raw_value": "1 mV s-1", "value": 1, "unit": "mV/s", "qualifier": "exact"},
                "evidence": ev,
            },
            "metrics": [
                {
                    "property": "corrosion_current_density",
                    "quantity": {"raw_value": "2.4 µA cm-2", "value": 2.4, "unit": "µA/cm2", "qualifier": "exact"},
                    "ownership": "focal_work",
                    "evidence": ev,
                },
                {
                    "property": "inhibition_efficiency",
                    "quantity": {"raw_value": "88 %", "value": 88, "unit": "%", "qualifier": "exact"},
                    "ownership": "cited_prior_work",
                    "evidence": ev,
                },
            ],
            "ownership": "focal_work",
            "evidence": ev,
        }],
        "calculations": [{
            "calculation_id": "dft1",
            "calculation_type": "dft",
            "material_refs": ["steel"],
            "surface": "Fe(110)",
            "adsorbate_or_inhibitor": "organic inhibitor",
            "method": "DFT",
            "outputs": [{
                "property": "adsorption_energy",
                "quantity": {"raw_value": "-1.25 eV", "value": -1.25, "unit": "eV", "qualifier": "exact"},
                "evidence": ev,
            }],
            "ownership": "focal_work",
            "evidence": ev,
        }],
    })


def test_corrosion_archive_admits_focal_verified_metric_and_quarantines_cited_metric():
    archive = assemble_corrosion_archive(_document(), model="offline")
    assert archive.metadata.domain == "corrosion"
    assert len(archive.materials) == 1
    assert len(archive.experiments) == 1
    outputs = archive.experiments[0].outputs
    assert [item.property for item in outputs] == ["corrosion_current_density"]
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    assert audit["admitted_quantitative_values"] == 1
    assert any(item["reason"] == "ownership_cited_prior_work" for item in audit["quarantine"])
    assert archive.quality.validation_status == "schema_validated"


def test_corrosion_archive_preserves_linked_inhibitor_name_and_concentration_as_conditions():
    archive = assemble_corrosion_archive(_document())
    conditions = {item.property: item for item in archive.experiments[0].conditions}
    assert conditions["treatment"].value == "organic inhibitor"
    assert conditions["inhibitor"].value == "organic inhibitor"
    assert conditions["treatment_concentration"].raw_value == "1×10^-3 M"
    assert conditions["inhibitor_concentration"].raw_value == "1×10^-3 M"
    assert all(item.evidence and item.evidence[0].verbatim_match is True for item in (
        conditions["treatment"],
        conditions["inhibitor"],
        conditions["treatment_concentration"],
        conditions["inhibitor_concentration"],
    ))


def test_corrosion_archive_keeps_dft_separate_from_experiments():
    archive = assemble_corrosion_archive(_document())
    assert len(archive.calculations) == 1
    calculation = archive.calculations[0]
    assert calculation.calculation_type == "dft"
    assert calculation.outputs[0].property == "adsorption_energy"
    assert all(experiment.experiment_type != "dft" for experiment in archive.experiments)
    assert any(rel.predicate == "calculated_for" for rel in archive.relationships)


def test_corrosion_potential_without_reference_is_quarantined_not_canonical():
    document = _document()
    experiment = document.experiments[0]
    experiment.polarization_conditions.reference_electrode = None
    experiment.metrics = [experiment.metrics[0].model_copy(update={
        "property": "corrosion_potential",
        "quantity": experiment.metrics[0].quantity.model_copy(update={"raw_value": "-0.52 V", "value": -0.52, "unit": "V"}),
    })]
    archive = assemble_corrosion_archive(document)
    assert archive.experiments[0].outputs == []
    audit = archive.domain_payloads[0].values["admissibility_audit"]
    assert any(item["reason"] == "missing_reference_electrode" for item in audit["quarantine"])


def test_corrosion_relationships_resolve_only_to_canonical_ids():
    archive = assemble_corrosion_archive(_document())
    known = {
        archive.metadata.archive_id,
        *(item.source_id for item in archive.sources),
        *(item.material_id for item in archive.materials),
        *(item.process_id for item in archive.processes),
        *(item.experiment_id for item in archive.experiments),
        *(item.calculation_id for item in archive.calculations),
    }
    assert all(rel.subject_id in known and rel.object_id in known for rel in archive.relationships)
