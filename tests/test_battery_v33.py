from synthex_platform.extraction.battery_models import (
    BatteryDocument, BatterySource, BatteryGroup, BatteryQuantity, ChargeProtocol,
    DischargeProtocol, ImpedanceProtocol, BatteryEvidence, BatteryMaterial, BatterySynthesis,
    BatteryProcessStep, SharedBatteryProtocol, ElectrodeFabrication, CellAssembly,
    ElectrochemicalTesting, BatteryPerformancePoint,
)
from synthex_platform.extraction.battery_postprocess import deduplicate_shared_protocols
from synthex_platform.extraction.battery_assembler import assemble_battery_archive
from synthex_v2.pdf_utils_v2 import extract_pages, pages_to_marked_text


def q(v, u):
    return BatteryQuantity(raw_value=f"{v} {u}", value=v, unit=u, qualifier="exact")


def test_repeated_protocols_are_promoted_to_shared_reference():
    protocol = dict(
        charge_protocol=ChargeProtocol(mode="CC-CV", constant_current=q(1.5,"A"), voltage_limit=q(4.2,"V"), cutoff_current=q(20,"mA")),
        discharge_protocol=DischargeProtocol(mode="CC", current=q(4,"A"), cutoff_voltages=[q(2.2,"V"),q(2.5,"V")]),
        impedance_protocol=ImpedanceProtocol(method="EIS", frequency_min=q(0.1,"Hz"), frequency_max=q(5,"kHz")),
    )
    doc=BatteryDocument(source=BatterySource(title="NASA"), battery_groups=[
        BatteryGroup(group_id="a", battery_ids=["B1"], **protocol),
        BatteryGroup(group_id="b", battery_ids=["B2"], **protocol),
    ])
    out=deduplicate_shared_protocols(doc)
    assert len(out.shared_protocols)==1
    assert out.battery_groups[0].protocol_refs == out.battery_groups[1].protocol_refs
    assert out.battery_groups[0].charge_protocol is None


def test_materials_paper_assembles_processes_and_quality():
    ev=BatteryEvidence(page=2, section="Methods", text_snippet="Li2FeTiO4 was synthesized by sol-gel.", source_type="text")
    mat=BatteryMaterial(
        material_id="lfto", formula="Li2FeTiO4", role="cathode", ownership="focal_work",
        synthesis=BatterySynthesis(method="sol-gel", precursors=["citric acid","FeCl2·4H2O"], steps=[
            BatteryProcessStep(step="precalcination", temperature=q(500,"°C"), duration=q(8,"h"), atmosphere="Ar", evidence=ev),
            BatteryProcessStep(step="calcination", temperature=q(700,"°C"), evidence=ev),
        ], evidence=[ev])
    )
    ef=ElectrodeFabrication(active_material="Li2FeTiO4", active_material_fraction=q(80,"%"), conductive_additive="acetylene black", conductive_fraction=q(10,"%"), binder="PVDF", binder_fraction=q(10,"%"), current_collector="Al foil", coating_method="doctor blade", evidence=[ev])
    ca=CellAssembly(cell_format="CR2032", counter_electrode="Li foil", separator="Celgard 2400", electrolyte_volume=q(100,"µL"), atmosphere="Ar", evidence=[ev])
    et=ElectrochemicalTesting(cv_scan_rate=q(0.1,"mV/s"), voltage_min=q(1.5,"V"), voltage_max=q(4.8,"V"), long_term_cycles=100, long_term_c_rate="1 C", evidence=[ev])
    shared=SharedBatteryProtocol(protocol_id="p1", ownership="focal_work", electrode_fabrication=ef, cell_assembly=ca, electrochemical_testing=et, evidence=[ev])
    group=BatteryGroup(group_id="700C", ownership="focal_work", material_ref="lfto", variant_label="700 °C", calcination_temperature=q(700,"°C"), protocol_refs=["p1"], performance_points=[
        BatteryPerformancePoint(property="specific_capacity", raw_value="121.3 mAh/g", value=121.3, unit="mAh/g", cycle=1, ownership="focal_work", evidence=ev),
        BatteryPerformancePoint(property="capacity_retention", raw_value="89.2%", value=89.2, unit="%", cycle=100, ownership="focal_work", evidence=ev),
    ], evidence=[ev])
    doc=BatteryDocument(source=BatterySource(title="LFT paper", year=2025), paper_types=["materials_synthesis","electrode_fabrication","cell_assembly","electrochemical_performance"], materials=[mat], shared_protocols=[shared], battery_groups=[group])
    arc=assemble_battery_archive(
        doc, model="test", source_text="--- PAGE 2 ---\nLi2FeTiO4 was synthesized by sol-gel."
    )
    assert arc.materials and arc.processes and arc.devices and arc.experiments
    assert arc.quality.completeness == 1.0
    assert arc.quality.provenance_coverage > 0
    assert arc.quality.unit_normalization_coverage > 0.8
    assert any(r.predicate == "contains_material" for r in arc.relationships)


def test_true_electrode_material_gold_fixture_validates_and_assembles():
    import json
    from pathlib import Path
    p=Path(__file__).parents[1]/"benchmark"/"batteries_v1"/"batteries_11_00142_gold_document.json"
    doc=BatteryDocument.model_validate(json.loads(p.read_text(encoding="utf-8")))
    for material in doc.materials:
        material.ownership = "focal_work"
    for protocol in doc.shared_protocols:
        protocol.ownership = "focal_work"
    for group in doc.battery_groups:
        group.ownership = "focal_work"
        for point in group.performance_points:
            point.ownership = "focal_work"
    pdf=Path(__file__).parents[1]/"benchmark"/"batteries_v1"/"corpus_pdfs"/"batteries-11-00142.pdf"
    arc=assemble_battery_archive(doc, model="gold", source_text=pages_to_marked_text(extract_pages(pdf)))
    assert len(doc.materials)==1
    assert len(doc.battery_groups)==3
    assert len(doc.shared_protocols)==1
    assert any(o.property=="specific_capacity" and o.value==121.3 for e in arc.experiments for o in e.outputs)
    assert any(o.property=="diffusion_coefficient" and o.value==1.096e-12 for e in arc.experiments for o in e.outputs)
    assert arc.quality.completeness == 1.0
    assert arc.quality.provenance_coverage > 0.4
    assert arc.quality.unit_normalization_coverage > 0.85
