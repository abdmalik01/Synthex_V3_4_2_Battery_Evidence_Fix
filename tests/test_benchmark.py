import json
from pathlib import Path
from synthex_v2.models import SensorRecord
from synthex_v2.batch import merge_records
from synthex_v2.visualizations import selectivity_matrix, response_time_points


def load_benchmark():
    p=Path(__file__).parents[1]/'benchmark'/'expected_records.json'
    return [SensorRecord.model_validate(x) for x in json.loads(p.read_text(encoding='utf-8'))]


def test_benchmark_replay_loads_and_aggregates():
    records=load_benchmark()
    assert len(records)==4
    merged=merge_records(records)
    assert len(merged.samples)>=6
    rt=response_time_points(merged)
    assert not rt.empty
    matrix=selectivity_matrix(merged)
    assert not matrix.empty
