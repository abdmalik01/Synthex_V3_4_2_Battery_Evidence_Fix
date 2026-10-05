from __future__ import annotations

import pytest

from synthex_platform.core.models import Evidence, Measurement
from synthex_platform.core.registry import DomainRegistry
from synthex_platform.extraction.draft_models import DraftDevice, DraftDeviceLayer
from synthex_platform.extraction.photovoltaics_contract import (
    PV_PROPERTIES,
    photovoltaics_admission_decision,
    photovoltaics_device_decision,
)
from synthex_platform.extraction.router import DomainRouter


def _measurement(
    property_name: str,
    raw: str,
    value: float,
    unit: str,
    *,
    conditions: dict | None = None,
    source_type: str = "table",
) -> Measurement:
    return Measurement(
        property=property_name,
        raw_value=raw,
        value=value,
        unit=unit,
        conditions={"scientific_type": "reported_measurement", **(conditions or {})},
        evidence=[Evidence(
            page=2,
            source_type=source_type,
            verbatim_match=True,
            text_snippet=raw,
            table_id="table-2",
            locator="row=device;column=value",
        )],
    )


def test_photovoltaics_manifest_and_contract_cover_device_performance_spectral_stability_and_process_context():
    manifest = DomainRegistry().get("photovoltaics")
    keys = {item["key"] for item in manifest["properties"]}
    assert manifest["version"] == "1.3.0"
    assert {
        "power_conversion_efficiency", "open_circuit_voltage",
        "short_circuit_current_density", "short_circuit_current", "fill_factor",
        "voltage_at_maximum_power", "stabilized_power_conversion_efficiency",
        "swept_power_conversion_efficiency", "initial_power_conversion_efficiency",
        "aged_power_conversion_efficiency",
        "external_quantum_efficiency", "incident_photon_to_current_efficiency",
        "retained_efficiency", "degradation_rate", "t80", "t90",
        "eqe_integrated_current_density", "calculated_bandgap",
        "calculated_absorption_coefficient", "carrier_effective_mass",
        "defect_formation_energy", "simulated_power_conversion_efficiency",
        "simulated_open_circuit_voltage", "predicted_short_circuit_current_density",
        "simulated_fill_factor",
        "active_area", "irradiance", "processing_time", "film_thickness",
    } <= keys
    assert manifest["scientific_contract"]["performance_requires"] == [
        "device association", "illumination_spectrum", "irradiance",
    ]


@pytest.mark.parametrize(
    "text,expected_type,signal",
    [
        (
            "We fabricated perovskite solar cells and measured power conversion efficiency, "
            "open-circuit voltage, short-circuit current density and fill factor under AM 1.5 G.",
            "photovoltaic_performance",
            "pv_device_performance_context",
        ),
        (
            "The photovoltaic device external quantum efficiency (EQE) was measured as a function "
            "of wavelength from 350 nm to 850 nm.",
            "spectral_response",
            "pv_spectral_wavelength_context",
        ),
    ],
)
def test_strong_photovoltaic_combinations_route_to_photovoltaics(text, expected_type, signal):
    route = DomainRouter().route_text(text)
    assert route.domain == "photovoltaics"
    assert expected_type in route.paper_types
    assert signal in route.focal_signals["photovoltaics"]


@pytest.mark.parametrize(
    "text",
    [
        "Efficiency, current, voltage, stability, layers and electrodes were discussed generically.",
        "A semiconductor thin film layer showed a band gap and improved carrier mobility.",
    ],
)
def test_weak_generic_or_semiconductor_language_does_not_route_to_photovoltaics(text):
    try:
        route = DomainRouter().route_text(text)
    except ValueError:
        return
    assert route.domain != "photovoltaics"


def test_battery_context_owns_shared_current_voltage_efficiency_language():
    route = DomainRouter().route_text(
        "We assembled lithium-ion battery cathode electrodes and measured charge-discharge current, "
        "voltage, coulombic efficiency, capacity retention and electrochemical impedance."
    )
    assert route.domain == "batteries"


def test_pv_admission_requires_value_specific_primary_evidence_and_performance_context():
    context = {"illumination_spectrum": "AM 1.5 G", "irradiance": 100.0}
    admitted = _measurement("power_conversion_efficiency", "13.387", 13.387, "%", conditions=context)
    no_light = _measurement("power_conversion_efficiency", "13.387", 13.387, "%")
    caption = _measurement(
        "power_conversion_efficiency", "13.387", 13.387, "%",
        conditions=context, source_type="figure_caption",
    )
    wrong_unit = _measurement(
        "open_circuit_voltage", "0.931", 0.931, "%", conditions=context,
    )
    assert photovoltaics_admission_decision(admitted, role="result").admitted
    assert photovoltaics_admission_decision(no_light, role="result").reason == "missing_required_condition_illumination_spectrum"
    assert photovoltaics_admission_decision(caption, role="result").reason == "no_value_specific_verbatim_evidence"
    assert photovoltaics_admission_decision(wrong_unit, role="result").reason == "invalid_unit_for_voltage"


def test_percent_properties_and_time_to_threshold_remain_scientifically_distinct():
    context = {"illumination_spectrum": "AM 1.5 G", "irradiance": 100.0}
    pce = _measurement("power_conversion_efficiency", "12.6", 12.6, "%", conditions=context)
    ff = _measurement("fill_factor", "56.0", 56.0, "%", conditions=context)
    t80 = _measurement(
        "t80", "500 h", 500.0, "h",
        conditions={"aging_protocol": "ISOS-D-2", "temperature": 85.0, "atmosphere": "ambient air"},
    )
    assert photovoltaics_admission_decision(pce, role="result").admitted
    assert photovoltaics_admission_decision(ff, role="result").admitted
    assert photovoltaics_admission_decision(t80, role="result").admitted
    assert PV_PROPERTIES["power_conversion_efficiency"] is not PV_PROPERTIES["fill_factor"]
    assert PV_PROPERTIES["t80"].unit_family == "time"
    assert PV_PROPERTIES["retained_efficiency"].required_conditions == ("aging_time",)


def test_official_source_data_workbook_cell_is_value_specific_primary_evidence():
    measurement = Measurement(
        property="external_quantum_efficiency",
        raw_value="89.37687",
        value=89.37687,
        unit="%",
        conditions={
            "scientific_type": "reported_measurement",
            "wavelength": 570.0,
            "wavelength_unit": "nm",
        },
        evidence=[Evidence(
            source_type="table",
            original_source_type="official_source_data_workbook",
            verbatim_match=True,
            text_snippet="89.37687",
            table_id="Fig. 3b",
            locator="sheet=Fig. 3b;wavelength_cell=A30;value_cell=B30",
        )],
    )
    assert photovoltaics_admission_decision(measurement, role="result").admitted


def test_photocatalysis_eqe_wavelength_language_does_not_claim_photovoltaics():
    route = DomainRouter().route_text(
        "The photocatalyst was tested in a batch reactor under solar irradiation. "
        "Photocatalysis conversion and product selectivity were measured together with "
        "wavelength-dependent EQE; only suspended catalyst particles were used."
    )
    assert route.domain == "catalysis"
    assert "pv_spectral_wavelength_context" not in route.focal_signals["photovoltaics"]


@pytest.mark.parametrize(
    "text,expected_domain",
    [
        (
            "A lithium-ion battery cathode electrode was cycled by charge-discharge current "
            "and voltage with coulombic efficiency and capacity retention.",
            "batteries",
        ),
        (
            "Potentiodynamic polarization measured corrosion current density, corrosion "
            "potential and pitting in chloride solution on a protective coating electrode.",
            "corrosion",
        ),
        (
            "Tensile testing measured yield strength, ultimate tensile strength and elongation "
            "at break for layered specimens.",
            "mechanical",
        ),
        (
            "Laser powder bed fusion used laser power, scan speed and layer thickness; relative "
            "density, porosity and yield strength were measured.",
            "additive_manufacturing",
        ),
    ],
)
def test_cross_domain_current_voltage_layer_language_does_not_contaminate_pv(text, expected_domain):
    assert DomainRouter().route_text(text).domain == expected_domain


def test_semiconductor_wavelength_current_voltage_without_pv_device_stays_outside_pv():
    route = DomainRouter().route_text(
        "A semiconductor thin film transistor measured carrier mobility, band gap, current "
        "and voltage as a function of wavelength."
    )
    assert route.domain != "photovoltaics"


def test_device_contract_preserves_contiguous_order_and_functional_roles():
    device = DraftDevice(
        local_id="d1",
        device_type="solar_cell",
        ownership="focal_work",
        layer_stack=[
            DraftDeviceLayer(sequence_index=0, role="substrate", material_ref="same"),
            DraftDeviceLayer(sequence_index=1, role="transparent_electrode", material_ref="same"),
            DraftDeviceLayer(sequence_index=2, role="absorber", material_ref="absorber"),
            DraftDeviceLayer(sequence_index=3, role="electrode", material_ref="same"),
        ],
    )
    assert photovoltaics_device_decision(device).admitted
    invalid = device.model_copy(update={
        "layer_stack": [
            DraftDeviceLayer(sequence_index=0, role="substrate", material_ref="same"),
            DraftDeviceLayer(sequence_index=2, role="absorber", material_ref="absorber"),
        ]
    })
    assert photovoltaics_device_decision(invalid).reason == "noncontiguous_layer_sequence"
