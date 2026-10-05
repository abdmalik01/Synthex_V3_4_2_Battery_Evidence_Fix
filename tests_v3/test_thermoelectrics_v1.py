from __future__ import annotations

import pytest

from synthex_platform.core.models import Evidence, Measurement, SourceType
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftExperiment, DraftMaterial, DraftSource, ExtractedDocument,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.thermoelectrics_contract import (
    TE_PROPERTIES, thermoelectrics_admission_decision,
)


def _evidence(raw: str = "190.8") -> Evidence:
    return Evidence(
        source_type=SourceType.supplementary,
        original_source_type="official_source_data_workbook",
        verbatim_match=True,
        text_snippet=f"Figure 5b!F2={raw} uV/K",
        table_id="fig5b",
        locator="sheet=Figure 5b;cell=F2",
    )


def _seebeck(**updates) -> Measurement:
    payload = {
        "property": "seebeck_coefficient",
        "raw_value": "190.8",
        "value": 190.8,
        "unit": "uV/K",
        "conditions": {
            "scientific_type": "reported_measurement",
            "temperature": 311.7,
            "temperature_unit": "K",
            "measurement_orientation": "parallel to SPS direction",
            "carrier_type": "p-type",
            "seebeck_sign": "positive",
            "absolute_value": False,
        },
        "evidence": [_evidence()],
    }
    payload.update(updates)
    return Measurement(**payload)


def test_manifest_and_contract_cover_core_transport_identity_and_processing():
    manifest = DomainRegistry().get("thermoelectrics")
    keys = {item["key"] for item in manifest["properties"]}
    assert manifest["version"] == "1.1.0"
    assert {
        "seebeck_coefficient", "electrical_conductivity", "electrical_resistivity",
        "total_thermal_conductivity", "lattice_thermal_conductivity",
        "electronic_thermal_conductivity", "power_factor", "zt",
        "carrier_concentration", "carrier_mobility", "sintering_temperature", "sintering_pressure",
    }.issubset(keys)
    assert {
        "seebeck_coefficient", "electrical_conductivity", "electrical_resistivity",
        "total_thermal_conductivity", "lattice_thermal_conductivity",
        "electronic_thermal_conductivity", "power_factor", "zt",
    }.issubset(TE_PROPERTIES)
    assert manifest["scientific_contract"]["thermal_conductivity_components"] == [
        "total_thermal_conductivity", "lattice_thermal_conductivity",
        "electronic_thermal_conductivity",
    ]


def test_strong_temperature_dependent_transport_context_routes_to_thermoelectrics():
    route = DomainRouter().route_text(
        "We synthesized p-type Na-doped SnSe thermoelectric material by spark plasma sintering. "
        "We measured temperature-dependent Seebeck coefficient, electrical conductivity, lattice "
        "thermal conductivity, power factor and zT as a function of temperature."
    )
    assert route.domain == "thermoelectrics"
    assert "te_transport_performance_context" in route.focal_signals["thermoelectrics"]
    assert "te_temperature_series_context" in route.focal_signals["thermoelectrics"]
    assert {"electrical_transport", "thermal_transport", "thermoelectric_performance"}.issubset(route.paper_types)


@pytest.mark.parametrize("text", [
    "A K-type thermocouple measured the furnace temperature during annealing.",
    "The transistor power factor, carrier mobility, and electrical conductivity were optimized.",
    "Seebeck was cited as an example in this review of semiconductor sensors.",
])
def test_weak_incidental_or_non_te_language_does_not_claim_thermoelectrics(text):
    try:
        route = DomainRouter().route_text(text)
    except ValueError:
        return
    assert route.domain != "thermoelectrics"


def test_admission_requires_sign_temperature_orientation_type_and_value_evidence():
    assert thermoelectrics_admission_decision(_seebeck(), role="result").admitted
    wrong_sign = _seebeck(conditions={**_seebeck().conditions, "seebeck_sign": "negative"})
    absolute = _seebeck(conditions={**_seebeck().conditions, "absolute_value": True})
    no_temperature = _seebeck(conditions={key: value for key, value in _seebeck().conditions.items() if key != "temperature"})
    no_orientation = _seebeck(conditions={key: value for key, value in _seebeck().conditions.items() if key != "measurement_orientation"})
    bad_evidence = _seebeck(evidence=[_evidence("191.9")])
    assert thermoelectrics_admission_decision(wrong_sign, role="result").reason == "seebeck_sign_mismatch"
    assert thermoelectrics_admission_decision(absolute, role="result").reason == "absolute_seebeck_not_canonical"
    assert thermoelectrics_admission_decision(no_temperature, role="result").reason == "missing_or_invalid_temperature"
    assert thermoelectrics_admission_decision(no_orientation, role="result").reason == "missing_measurement_orientation"
    assert thermoelectrics_admission_decision(bad_evidence, role="result").reason == "no_value_specific_verbatim_evidence"


def test_computational_values_require_calculated_type_and_never_become_experiments():
    reported = thermoelectrics_admission_decision(
        _seebeck(), role="result", modality="computational"
    )
    calculated_measurement = _seebeck(
        conditions={**_seebeck().conditions, "scientific_type": "calculated"}
    )
    calculated = thermoelectrics_admission_decision(
        calculated_measurement, role="result", modality="computational"
    )
    assert not reported.admitted
    assert reported.reason == "computational_output_must_be_calculated"
    assert calculated.admitted


def test_thermal_components_and_measured_vs_derived_cannot_collapse():
    common = {
        "raw_value": "0.07805", "value": 0.07805, "unit": "W/m/K",
        "conditions": {
            "scientific_type": "reported_derived_metric", "temperature": 783.4,
            "temperature_unit": "K", "measurement_orientation": "parallel to SPS direction",
            "derivation_basis": "kappa_total minus kappa_electronic",
        },
        "evidence": [Evidence(
            source_type=SourceType.supplementary,
            original_source_type="official_source_data_workbook", verbatim_match=True,
            text_snippet="Figure 4d!J13=0.07805 W/m/K", table_id="fig4d", locator="cell=J13",
        )],
    }
    lattice = Measurement(property="lattice_thermal_conductivity", **common)
    total = Measurement(property="total_thermal_conductivity", **common)
    measured_lattice = lattice.model_copy(update={"conditions": {**lattice.conditions, "scientific_type": "reported_measurement"}})
    no_derivation = total.model_copy(update={"conditions": {key: value for key, value in total.conditions.items() if key != "derivation_basis"}})
    assert thermoelectrics_admission_decision(lattice, role="result").admitted
    assert thermoelectrics_admission_decision(total, role="result").admitted
    assert thermoelectrics_admission_decision(measured_lattice, role="result").reason == "invalid_or_missing_scientific_type"
    assert thermoelectrics_admission_decision(no_derivation, role="result").reason == "missing_derivation_basis"


def test_assembler_requires_one_admitted_material_per_te_experiment():
    evidence = Evidence(
        page=1, section="Results", source_type=SourceType.text, verbatim_match=True,
        text_snippet="Na0.03Sn0.965Se was measured.", locator="page=1",
    )
    draft = ExtractedDocument(
        source=DraftSource(title="TE test"),
        materials=[
            DraftMaterial(local_id="a", formula="Na0.03Sn0.965Se", ownership="focal_work", evidence=[evidence]),
            DraftMaterial(local_id="b", formula="SnSe", ownership="focal_work", evidence=[evidence]),
        ],
        experiments=[DraftExperiment(
            local_id="ambiguous", experiment_type="thermoelectric_transport",
            material_refs=["a", "b"], outputs=[_seebeck()],
            ownership="focal_work", evidence=[evidence],
        )],
    )
    archive = assemble_archive(draft, domain="thermoelectrics")
    assert not archive.experiments
    quarantine = archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]
    assert any(item["reason"] == "ambiguous_or_missing_material_association" for item in quarantine)
