"""Build replay fixtures from published sensor results.

These records are NOT Gemini outputs. They are compact expected-value fixtures derived from
published source pages and are used to test schema handling and visualizations without inventing data.
"""
from pathlib import Path
from synthex_v2.models import (
    SensorRecord, PaperInfo, SampleRecord, TestingConditions, PerformanceInfo,
    SensorResponse, Selectivity, SelectivityEntry, LimitOfDetection, TimeMetric,
    Quantity, Evidence, Sensitivity, DepositionInfo,
)

OUT = Path(__file__).with_name('expected_records.json')


def q(v, unit, raw=None):
    return Quantity(raw_value=raw or f"{v} {unit}", value=v, unit=unit)

records = [
    SensorRecord(
        paper=PaperInfo(
            title='Selective Reduction Laser Sintering: A New Strategy for NO2 Gas Detection Based on In2O3 Nanoparticles',
            doi='10.1002/adfm.202419057', year=2025,
            url='https://advanced.onlinelibrary.wiley.com/doi/10.1002/adfm.202419057',
        ),
        samples=[SampleRecord(
            sample_id='SRLS-In2O3', material='In2O3 nanoparticles', material_category='Metal Oxides',
            sensor_type='Chemiresistive gas sensor', transduction_method='Resistance change',
            deposition=DepositionInfo(method_family='Laser processing', method='Selective reduction laser sintering', method_variant='UV selective reduction laser sintering'),
            testing_conditions=TestingConditions(target_analyte='NO2', concentration=q(10, 'ppm'), atmosphere='room temperature'),
            performance=PerformanceInfo(
                sensor_response=SensorResponse(value=Quantity(raw_value='S = 460.9', value=460.9, unit='dimensionless')),
                sensitivity=Sensitivity(value=Quantity(raw_value='56.91 ppm^-1', value=56.91, unit='ppm^-1'), concentration_range='2–10 ppm'),
                selectivity=Selectivity(target_analyte='NO2', entries=[SelectivityEntry(interferent='C2H5OH / CO2 / acetone / NH3 / CH4 / H2S', raw_ratio='>400', selectivity_ratio=None)]),
                response_time=TimeMetric(value=q(27, 's'), analyte='NO2', concentration=q(10, 'ppm')),
                recovery_time=TimeMetric(value=q(570, 's'), analyte='NO2', concentration=q(10, 'ppm')),
            )
        )]
    ),
    SensorRecord(
        paper=PaperInfo(
            title='Au/ZnO/In2O3 nanoparticles for enhanced isopropanol gas sensing performance',
            doi='10.1039/D3RA07507A', year=2024,
            url='https://pubs.rsc.org/en/Content/ArticleHtml/2024/RA/d3ra07507a',
        ),
        samples=[SampleRecord(
            sample_id='2%Au/1%ZnO/In2O3', material='Au/ZnO/In2O3', material_category='Metal Oxides',
            sensor_type='Chemiresistive gas sensor', transduction_method='Resistance change',
            testing_conditions=TestingConditions(target_analyte='Isopropanol', concentration=q(100, 'ppm')),
            performance=PerformanceInfo(
                response_time=TimeMetric(value=q(78, 's'), criterion='t90', analyte='Isopropanol', concentration=q(100, 'ppm')),
                recovery_time=TimeMetric(value=q(49, 's'), criterion='t90', analyte='Isopropanol', concentration=q(100, 'ppm')),
            )
        )]
    ),
    SensorRecord(
        paper=PaperInfo(
            title='Ni–In2O3/ZnO MEMS H2S gas sensor',
            doi='10.1515/znb-2024-0113', year=2025,
            url='https://www.degruyterbrill.com/document/doi/10.1515/znb-2024-0113/pdf?licenseType=free',
        ),
        samples=[SampleRecord(
            sample_id='Ni-In2O3/ZnO', material='Ni–In2O3/ZnO', material_category='Metal Oxides',
            sensor_type='MEMS chemiresistive gas sensor',
            testing_conditions=TestingConditions(target_analyte='H2S', concentration=q(100, 'ppm'), operating_temperature=q(300, '°C')),
            performance=PerformanceInfo(
                limit_of_detection=LimitOfDetection(value=q(0.57, 'ppm'), calculation_method='Reported by authors'),
                response_time=TimeMetric(value=q(4.4, 's'), analyte='H2S', concentration=q(100, 'ppm'), operating_temperature=q(300, '°C')),
                recovery_time=TimeMetric(value=q(5.2, 's'), analyte='H2S', concentration=q(100, 'ppm'), operating_temperature=q(300, '°C')),
                selectivity=Selectivity(target_analyte='H2S', qualitative_statement='Specific selectivity for H2S versus tested interfering gases.'),
            )
        )]
    ),
    SensorRecord(
        paper=PaperInfo(
            title='Defect-Driven Selectivity Inversion in ZnO Gas Sensors via Y3+ and Dy3+ Doping for Enhanced VOC Detection with a Suppressed NO2 Response',
            doi='10.3390/s26154675', year=2026,
            url='https://www.mdpi.com/1424-8220/26/15/4675',
        ),
        samples=[
            SampleRecord(sample_id='ZnO-NO2', material='ZnO', material_category='Metal Oxides', sensor_type='Chemiresistive gas sensor', testing_conditions=TestingConditions(target_analyte='NO2', concentration=q(25,'ppm'), operating_temperature=q(230,'°C')), performance=PerformanceInfo(sensor_response=SensorResponse(value=q(30.0,'dimensionless')), response_time=TimeMetric(value=q(343.40,'s'), criterion='t90', analyte='NO2', concentration=q(25,'ppm'), operating_temperature=q(230,'°C')), recovery_time=TimeMetric(value=q(705.68,'s'), criterion='t90'))),
            SampleRecord(sample_id='ZD4-Ethanol', material='Dy-doped ZnO', material_category='Metal Oxides', sensor_type='Chemiresistive gas sensor', testing_conditions=TestingConditions(target_analyte='Ethanol', concentration=q(25,'ppm'), operating_temperature=q(279,'°C')), performance=PerformanceInfo(sensor_response=SensorResponse(value=q(9.61,'dimensionless')), selectivity=Selectivity(target_analyte='Ethanol', entries=[SelectivityEntry(interferent='NO2', raw_ratio='5.6×', selectivity_ratio=5.6)]), response_time=TimeMetric(value=q(30.43,'s'), criterion='t90', analyte='Ethanol', concentration=q(25,'ppm'), operating_temperature=q(279,'°C')), recovery_time=TimeMetric(value=q(284.67,'s'), criterion='t90'))),
            SampleRecord(sample_id='ZY4-Acetone', material='Y-doped ZnO', material_category='Metal Oxides', sensor_type='Chemiresistive gas sensor', testing_conditions=TestingConditions(target_analyte='Acetone', concentration=q(25,'ppm'), operating_temperature=q(258,'°C')), performance=PerformanceInfo(sensor_response=SensorResponse(value=q(8.27,'dimensionless')), selectivity=Selectivity(target_analyte='Acetone', entries=[SelectivityEntry(interferent='NO2', raw_ratio='2×', selectivity_ratio=2.0)]), response_time=TimeMetric(value=q(12.19,'s'), criterion='t90', analyte='Acetone', concentration=q(25,'ppm'), operating_temperature=q(258,'°C')), recovery_time=TimeMetric(value=q(271.45,'s'), criterion='t90'))),
        ]
    ),
]

OUT.write_text('[\n' + ',\n'.join(r.model_dump_json(indent=2) for r in records) + '\n]', encoding='utf-8')
print(OUT)
