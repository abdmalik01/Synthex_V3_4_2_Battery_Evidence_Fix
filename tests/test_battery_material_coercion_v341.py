from synthex_platform.extraction.battery_models import BatteryDocument


def test_materials_paper_gemini_shape_is_coerced_without_data_loss():
    payload = {
        "source": {"title": "Example materials paper"},
        "paper_types": ["materials_synthesis", "electrode_fabrication", "cell_assembly", "electrochemical_performance", "impedance_eis"],
        "materials": [{
            "material_id": "m1", "formula": "Li2FeTiO4", "role": "cathode",
            "synthesis": {
                "method": "sol-gel",
                "steps": [{"step": 1, "temperature": "65 °C", "duration": "5 h", "details": "water bath"}],
                "calcination_temperatures": [600, 700, 800],
            },
        }],
        "shared_protocols": [{
            "protocol_id": "p1",
            "charge_protocol": "Galvanostatic charging with 1 C defined as 300 mA/g.",
            "discharge_protocol": "Galvanostatic discharge with 1 C defined as 300 mA/g.",
            "impedance_protocol": "Electrochemical impedance spectroscopy (EIS) measurements.",
            "electrochemical_testing": {
                "cv_scan_rate": "0.1 mV/s",
                "voltage_window": "1.5–4.8 V",
                "cycle_count": 100,
                "equipment": "CHI760E electrochemical workstation, LAND-CT2001A system",
            },
            "electrode_fabrication": {
                "active_material_fraction": "80 wt%",
                "conductive_additive": "10 wt% acetylene black",
                "binder": "10 wt% PVDF",
                "loading": "1.0 mg/cm2",
                "drying": "Dried at 80 °C for 12 h under vacuum, followed by vacuum drying at 120 °C for 6 h after punching.",
                "pressing": "Pressed at 10 MPa using a hydraulic press",
                "dimensions": "diameter of 10 mm",
            },
            "cell_assembly": {
                "format": "CR2032 coin cell",
                "electrolyte_volume": "100 µL",
                "glovebox_atmosphere": "argon-filled glovebox",
                "o2_limit": "< 0.1 ppm",
                "h2o_limit": "< 0.1 ppm",
            },
        }],
        "battery_groups": [{
            "group_id": "700", "material_ref": "m1", "protocol_refs": ["p1"],
            "performance_points": [
                {"property": "charge transfer resistance (Rct)", "value": 1258.6, "unit": "Ω"},
                {"property": "lithium-ion diffusion coefficient (DLi+)", "value": 1.096e-12, "unit": "cm2 s-1"},
                {"property": "discharge specific capacity", "value": 121.3, "unit": "mAh/g", "cycle": 1},
            ],
        }],
    }
    doc = BatteryDocument.model_validate(payload)
    syn = doc.materials[0].synthesis
    assert syn.steps[0].step == "1"
    assert syn.calcination_temperatures[1].unit == "°C"

    p = doc.shared_protocols[0]
    assert p.electrochemical_testing.voltage_min.value == 1.5
    assert p.electrochemical_testing.voltage_max.value == 4.8
    assert p.electrochemical_testing.long_term_cycles == 100
    assert len(p.electrochemical_testing.equipment) == 2
    assert p.electrode_fabrication.conductive_fraction.value == 10
    assert p.electrode_fabrication.binder_fraction.value == 10
    assert p.electrode_fabrication.pressing_pressure.value == 10
    assert p.electrode_fabrication.pressing_pressure.unit.lower() == "mpa"
    assert p.electrode_fabrication.disk_diameter.value == 10
    assert len(p.electrode_fabrication.drying_steps) == 2
    assert p.cell_assembly.cell_format == "CR2032 coin cell"
    assert p.cell_assembly.glovebox_o2.qualifier == "upper_bound"

    props = {x.property for x in doc.battery_groups[0].performance_points}
    assert "charge_transfer_resistance" in props
    assert "diffusion_coefficient" in props
    assert "specific_capacity" in props
