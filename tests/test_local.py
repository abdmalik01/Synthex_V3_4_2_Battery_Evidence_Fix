from synthex_v2.models import (
    SensorRecord, PaperInfo, SampleRecord, PerformanceInfo, TimeMetric, Quantity,
    TestingConditions, Selectivity, SelectivityEntry
)
from synthex_v2.normalizer import normalize_record
from synthex_v2.batch import merge_records, stamp_source
from synthex_v2.visualizations import selectivity_matrix, response_time_groups


def test_time_normalization_ms_to_seconds():
    r = SensorRecord(samples=[SampleRecord(performance=PerformanceInfo(response_time=TimeMetric(value=Quantity(value=450, unit='ms'))))])
    r = normalize_record(r)
    q = r.samples[0].performance.response_time.value
    assert q.normalized_value == 0.45
    assert q.normalized_unit == 's'


def test_batch_preserves_paper_provenance():
    a = SensorRecord(paper=PaperInfo(title='Paper A'), samples=[SampleRecord(sample_id='A1')])
    b = SensorRecord(paper=PaperInfo(title='Paper B'), samples=[SampleRecord(sample_id='B1')])
    merged = merge_records([a, b])
    assert [s.source_paper_title for s in merged.samples] == ['Paper A', 'Paper B']


def test_selectivity_matrix_uses_exact_numeric_ratios():
    r = SensorRecord(samples=[SampleRecord(
        sample_id='S1',
        performance=PerformanceInfo(selectivity=Selectivity(target_analyte='NO2', entries=[
            SelectivityEntry(interferent='CO', raw_ratio='5.6×', selectivity_ratio=5.6),
            SelectivityEntry(interferent='NH3', raw_ratio='>400', selectivity_ratio=None),
        ]))
    )])
    m = selectivity_matrix(r)
    assert float(m.loc['S1', 'NO2/CO']) == 5.6
    assert 'NO2/NH3' not in m.columns


def test_contour_groups_do_not_mix_materials():
    samples=[]
    for i,(t,c,rt) in enumerate([(100,1,40),(100,10,25),(200,1,20),(200,10,10)]):
        samples.append(SampleRecord(
            sample_id=f'A{i}', material='ZnO', sensor_type='Chemiresistive',
            testing_conditions=TestingConditions(target_analyte='NO2', concentration=Quantity(value=c, unit='ppm'), operating_temperature=Quantity(value=t, unit='°C')),
            performance=PerformanceInfo(response_time=TimeMetric(value=Quantity(value=rt, unit='s'), analyte='NO2'))
        ))
    # This extra different material must not be folded into the ZnO surface.
    samples.append(SampleRecord(
        sample_id='B', material='SnO2', sensor_type='Chemiresistive',
        testing_conditions=TestingConditions(target_analyte='NO2', concentration=Quantity(value=5, unit='ppm'), operating_temperature=Quantity(value=150, unit='°C')),
        performance=PerformanceInfo(response_time=TimeMetric(value=Quantity(value=99, unit='s'), analyte='NO2'))
    ))
    r=normalize_record(SensorRecord(samples=samples))
    groups=response_time_groups(r)
    assert len(groups)==1
    g=next(iter(groups.values()))
    assert set(g['material'])=={'ZnO'}
