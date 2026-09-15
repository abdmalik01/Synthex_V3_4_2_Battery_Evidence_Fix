from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.corrosion_models import CorrosionDocument
from synthex_platform.extraction.router import DomainRouter, classify_corrosion_paper_types


def test_corrosion_manifest_has_stage1_guardrails_and_core_properties():
    spec = DomainRegistry().get("corrosion")
    keys = {item["key"] for item in spec["properties"]}
    assert {
        "corrosion_rate",
        "corrosion_current_density",
        "corrosion_potential",
        "polarization_resistance",
        "charge_transfer_resistance",
        "inhibition_efficiency",
        "mass_loss",
        "pitting_potential",
    } <= keys
    guardrails = " ".join(spec.get("scientific_guardrails", [])).casefold()
    assert "reference electrode" in guardrails
    assert "silently convert" in guardrails
    assert "review" in guardrails
    assert "dft" in guardrails


def test_corrosion_router_prefers_corrosion_for_focal_polarization_eis_paper():
    text = """
    We prepared AA7075 specimens and polished the exposed surface before corrosion testing.
    Potentiodynamic polarization tests were carried out in 3.5 wt% NaCl solution using Ag/AgCl.
    Ecorr and icorr were obtained from the polarization curves and corrosion rate was reported.
    EIS measurements produced Nyquist plots and charge transfer resistance values after immersion.
    Pitting potential and passive film breakdown were also discussed.
    """
    route = DomainRouter().route_text(text)
    assert route.domain == "corrosion"
    assert route.scores["corrosion"] > route.scores["batteries"]
    assert "electrochemical_corrosion_context" in (route.focal_signals or {}).get("corrosion", [])
    assert "polarization_corrosion" in route.paper_types
    assert "impedance_eis" in route.paper_types


def test_corrosion_router_does_not_steal_battery_eis_paper():
    text = """
    We prepared a LiFePO4 cathode slurry with PVDF binder and assembled CR2032 coin cells in a glovebox.
    Charge-discharge cycling, specific capacity, coulombic efficiency and capacity retention were measured.
    Electrochemical impedance spectroscopy and Nyquist plots were used to examine the lithium-ion battery.
    """
    route = DomainRouter().route_text(text)
    assert route.domain == "batteries"


def test_corrosion_paper_types_are_multilabel():
    text = """
    The inhibitor concentration was varied and inhibition efficiency was obtained from weight loss tests.
    Potentiodynamic polarization provided Ecorr and icorr. Electrochemical impedance spectroscopy and
    an equivalent circuit yielded charge transfer resistance. DFT adsorption energy was calculated.
    """
    paper_types = classify_corrosion_paper_types(text)
    assert "inhibitor_study" in paper_types
    assert "polarization_corrosion" in paper_types
    assert "impedance_eis" in paper_types
    assert "computational_corrosion" in paper_types


def _valid_document_payload() -> dict:
    return {
        "source": {"title": "Example focal corrosion paper"},
        "paper_types": ["polarization_corrosion", "impedance_eis"],
        "materials": [
            {
                "local_id": "material_1",
                "reported_name": "AA7075",
                "material_class": "alloy",
                "role": "corroding_material",
                "ownership": "focal_work",
            }
        ],
        "surface_preparations": [
            {
                "preparation_id": "prep_1",
                "material_ref": "material_1",
                "polishing": "SiC paper",
                "ownership": "focal_work",
            }
        ],
        "environments": [
            {
                "environment_id": "env_1",
                "electrolyte": "3.5 wt% NaCl",
                "temperature": {"raw_value": "25 °C", "value": 25, "unit": "°C", "qualifier": "exact"},
            }
        ],
        "experiments": [
            {
                "experiment_id": "exp_1",
                "experiment_type": "potentiodynamic_polarization",
                "material_refs": ["material_1"],
                "environment_ref": "env_1",
                "polarization_conditions": {"reference_electrode": "Ag/AgCl"},
                "metrics": [
                    {
                        "property": "corrosion_potential",
                        "reported_term": "Ecorr",
                        "quantity": {"raw_value": "-0.72 V", "value": -0.72, "unit": "V", "qualifier": "exact"},
                        "ownership": "focal_work",
                    },
                    {
                        "property": "corrosion_current_density",
                        "reported_term": "icorr",
                        "quantity": {"raw_value": "4.2 µA cm-2", "value": 4.2, "unit": "uA/cm2", "qualifier": "exact"},
                        "ownership": "focal_work",
                    },
                ],
                "ownership": "focal_work",
            }
        ],
    }


def test_corrosion_document_accepts_source_tracked_focal_structure():
    document = CorrosionDocument.model_validate(_valid_document_payload())
    assert document.experiments[0].polarization_conditions.reference_electrode == "Ag/AgCl"
    assert document.experiments[0].metrics[0].quantity.raw_value == "-0.72 V"


def test_corrosion_document_rejects_unknown_material_reference():
    payload = _valid_document_payload()
    payload["experiments"][0]["material_refs"] = ["material_missing"]
    with pytest.raises(ValidationError, match="Unknown experiment material_refs"):
        CorrosionDocument.model_validate(payload)


def test_corrosion_condition_conflicts_cannot_be_silently_resolved():
    payload = _valid_document_payload()
    payload["condition_conflicts"] = [
        {
            "field": "electrolyte concentration",
            "reported_values": ["3.5 wt% NaCl", "0.6 M NaCl"],
            "resolved_value": "3.5 wt% NaCl",
        }
    ]
    with pytest.raises(ValidationError, match="must remain unresolved"):
        CorrosionDocument.model_validate(payload)


def test_computational_corrosion_stays_in_calculations():
    payload = _valid_document_payload()
    payload["calculations"] = [
        {
            "calculation_id": "calc_1",
            "calculation_type": "dft",
            "material_refs": ["material_1"],
            "surface": "Al(111)",
            "adsorbate_or_inhibitor": "inhibitor-X",
            "method": "DFT",
            "outputs": [
                {
                    "property": "adsorption_energy",
                    "quantity": {"raw_value": "-1.2 eV", "value": -1.2, "unit": "eV", "qualifier": "exact"},
                }
            ],
            "ownership": "focal_work",
        }
    ]
    document = CorrosionDocument.model_validate(payload)
    assert len(document.calculations) == 1
    assert all(metric.property != "adsorption_energy" for exp in document.experiments for metric in exp.metrics)
