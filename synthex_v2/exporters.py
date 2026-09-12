from __future__ import annotations
import json
import pandas as pd
from .models import SensorRecord


def to_json_bytes(record: SensorRecord) -> bytes:
    return json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")


def flatten_record(record: SensorRecord) -> pd.DataFrame:
    rows = []
    for i, sample in enumerate(record.samples):
        p, d, tc = sample.performance, sample.deposition, sample.testing_conditions
        base = {
            "paper_title": record.paper.title,
            "doi": record.paper.doi,
            "sample_id": sample.sample_id or f"sample_{i+1}",
            "material": sample.material,
            "material_category": sample.material_category,
            "sensor_type": sample.sensor_type,
            "target_analyte": tc.target_analyte if tc else None,
            "deposition_family": d.method_family if d else None,
            "deposition_method": d.method if d else None,
            "deposition_variant": d.method_variant if d else None,
            "substrate": d.substrate if d else None,
        }
        if p:
            if p.sensitivity and p.sensitivity.value:
                base.update(sensitivity_value=p.sensitivity.value.value, sensitivity_unit=p.sensitivity.value.unit, sensitivity_formula=p.sensitivity.formula)
            if p.limit_of_detection and p.limit_of_detection.value:
                base.update(lod_value=p.limit_of_detection.value.value, lod_unit=p.limit_of_detection.value.unit)
            if p.response_time and p.response_time.value:
                base.update(response_time_value=p.response_time.value.value, response_time_unit=p.response_time.value.unit, response_time_criterion=p.response_time.criterion)
            if p.recovery_time and p.recovery_time.value:
                base.update(recovery_time_value=p.recovery_time.value.value, recovery_time_unit=p.recovery_time.value.unit, recovery_time_criterion=p.recovery_time.criterion)
            if p.selectivity and p.selectivity.entries:
                for e in p.selectivity.entries:
                    row = dict(base)
                    row.update(selectivity_interferent=e.interferent, selectivity_ratio=e.selectivity_ratio,
                               selectivity_target_response=e.target_response, selectivity_interferent_response=e.interferent_response)
                    rows.append(row)
                continue
        rows.append(base)
    return pd.DataFrame(rows)
