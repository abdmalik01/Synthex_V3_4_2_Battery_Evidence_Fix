from .models import (
    SensorRecord, PaperInfo, SampleRecord, DepositionInfo, TestingConditions,
    PerformanceInfo, Quantity, Sensitivity, Selectivity, SelectivityEntry,
    LimitOfDetection, TimeMetric, Evidence
)


def build_demo_record() -> SensorRecord:
    # Illustrative values only; never presented as literature-derived data.
    configs = [
        ("S1", "RF Magnetron Sputtering", 150, 5, 28, 42, 18, 0.80, 4.2),
        ("S2", "RF Magnetron Sputtering", 200, 10, 20, 34, 22, 0.95, 3.1),
        ("S3", "Spin Coating", 250, 20, 15, 28, 14, 1.10, 5.0),
        ("S4", "Electrodeposition", 300, 40, 12, 23, 16, 1.25, 2.7),
        ("S5", "ALD", 225, 30, 18, 30, 20, 1.05, 3.6),
    ]
    samples = []
    for sid, method, temp, conc, rt, rec, sel, sens, lod in configs:
        evidence = Evidence(page=7, section="Gas sensing performance", text_snippet="Illustrative demo evidence; not from a real paper.", source_type="text", confidence=1.0)
        samples.append(SampleRecord(
            sample_id=sid,
            material="ZnO (demo)",
            material_category="Metal Oxides",
            sensor_type="Chemiresistive gas sensor",
            transduction_method="Resistance change",
            deposition=DepositionInfo(method_family="Demo family", method=method, substrate="Alumina", evidence=evidence),
            testing_conditions=TestingConditions(
                target_analyte="NO2",
                concentration=Quantity(raw_value=f"{conc} ppm", value=conc, unit="ppm", normalized_value=conc, normalized_unit="ppm"),
                operating_temperature=Quantity(raw_value=f"{temp} °C", value=temp, unit="°C", normalized_value=temp, normalized_unit="°C"),
            ),
            performance=PerformanceInfo(
                sensitivity=Sensitivity(reported_term="sensitivity", value=Quantity(raw_value=str(sens), value=sens, unit="a.u."), evidence=evidence),
                selectivity=Selectivity(target_analyte="NO2", entries=[
                    SelectivityEntry(interferent="CO", selectivity_ratio=sel, evidence=evidence),
                    SelectivityEntry(interferent="NH3", selectivity_ratio=sel*0.75, evidence=evidence),
                    SelectivityEntry(interferent="Ethanol", selectivity_ratio=sel*0.55, evidence=evidence),
                ], evidence=evidence),
                limit_of_detection=LimitOfDetection(value=Quantity(raw_value=f"{lod} ppb", value=lod, unit="ppb"), evidence=evidence),
                response_time=TimeMetric(value=Quantity(raw_value=f"{rt} s", value=rt, unit="s", normalized_value=rt, normalized_unit="s"), criterion="t90", analyte="NO2", concentration=Quantity(value=conc, unit="ppm", normalized_value=conc, normalized_unit="ppm"), operating_temperature=Quantity(value=temp, unit="°C", normalized_value=temp, normalized_unit="°C"), evidence=evidence),
                recovery_time=TimeMetric(value=Quantity(raw_value=f"{rec} s", value=rec, unit="s", normalized_value=rec, normalized_unit="s"), criterion="t90", analyte="NO2", concentration=Quantity(value=conc, unit="ppm", normalized_value=conc, normalized_unit="ppm"), operating_temperature=Quantity(value=temp, unit="°C", normalized_value=temp, normalized_unit="°C"), evidence=evidence),
            )
        ))
    return SensorRecord(
        paper=PaperInfo(title="Synthex V2 visualization demo — illustrative data only", year=2026),
        samples=samples,
        extraction_notes=["DEMO MODE: all values in this record are illustrative and are not extracted from literature."],
    )
