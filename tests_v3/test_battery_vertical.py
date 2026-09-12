from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.battery_models import (
    BatteryDocument, BatterySource, BatteryGroup, BatteryQuantity,
    BatteryEvidence, ChargeProtocol, DischargeProtocol, ImpedanceProtocol,
)
from synthex_platform.extraction.battery_assembler import assemble_battery_archive


def test_router_identifies_nasa_battery_style_paper():
    text = """
    Analysis and Performance Evaluation of Li-Ion Batteries Using NASA Battery Data Set.
    Charge data include voltage current temperature and time. Discharge includes capacity.
    Charging used constant current at 1.5 A to 4.2 V followed by constant voltage to 20 mA.
    Discharge used constant current at 4 A. Electrochemical Impedance Spectroscopy measured impedance.
    The work studies battery degradation and state of health.
    """
    route = DomainRouter().route_text(text)
    assert route.domain == "batteries"
    assert route.confidence > 0.7
    assert "electrochemical_performance" in route.paper_types
    assert "impedance_eis" in route.paper_types


def test_battery_document_assembles_devices_and_protocols():
    q = lambda raw, value, unit: BatteryQuantity(raw_value=raw, value=value, unit=unit, qualifier="exact")
    source_text = (
        "--- PAGE 1 ---\nAt 24Â°C, cells charged at 1.5A to 4.2V with a 20mA cutoff, "
        "discharged at 4A to 2.2V, 2.5V, or 2.7V, and EIS covered 0.1Hz to 5kHz."
    )
    evidence = [BatteryEvidence(page=1, source_type="text", text_snippet=source_text.split("\n", 1)[1])]
    doc = BatteryDocument(
        source=BatterySource(
            title="Analysis and Performance Evaluation of Li-Ion Batteries Using NASA Battery Data Set",
            dataset_source="NASA Prognostics Center of Excellence",
        ),
        paper_types=["electrochemical_performance", "battery_dataset_modelling", "impedance_eis"],
        battery_groups=[BatteryGroup(
            group_id="B25-28",
            ownership="focal_work",
            battery_ids=["B0025", "B0026", "B0027", "B0028"],
            temperature=q("24°C", 24, "°C"),
            charge_protocol=ChargeProtocol(
                mode="CC-CV",
                constant_current=q("1.5A", 1.5, "A"),
                voltage_limit=q("4.2V", 4.2, "V"),
                cutoff_current=q("20mA", 20, "mA"),
            ),
            discharge_protocol=DischargeProtocol(
                mode="CC",
                current=q("4A", 4, "A"),
                cutoff_voltages=[q("2.2V", 2.2, "V"), q("2.5V", 2.5, "V"), q("2.7V", 2.7, "V")],
            ),
            impedance_protocol=ImpedanceProtocol(
                method="Electrochemical Impedance Spectroscopy",
                frequency_min=q("0.1Hz", 0.1, "Hz"),
                frequency_max=q("5kHz", 5, "kHz"),
            ),
            measured_variables=["voltage", "current", "temperature", "time", "capacity", "impedance"],
            evidence=evidence,
        )],
    )
    archive = assemble_battery_archive(doc, model="test", source_text=source_text)
    assert archive.metadata.domain == "batteries"
    assert len(archive.devices) == 4
    assert len(archive.experiments) == 2
    props = {m.property for e in archive.experiments for m in e.conditions}
    assert {"temperature", "charge_current", "charge_voltage_limit", "charge_cutoff_current", "discharge_current", "frequency_min", "frequency_max"} <= props
    assert any(r.predicate == "tested_in" for r in archive.relationships)
