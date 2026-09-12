from __future__ import annotations
from .models import Quantity, SensorRecord

_TIME_TO_S = {"ms": 0.001, "millisecond": 0.001, "milliseconds": 0.001, "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0, "min": 60.0, "minute": 60.0, "minutes": 60.0}
_CONC_TO_PPM = {"ppm": 1.0, "ppb": 0.001, "ppt": 0.000001}
_TEMP_UNITS = {"°c", "c", "degc"}


def normalize_quantity(q: Quantity | None) -> Quantity | None:
    if q is None or q.value is None or not q.unit:
        return q
    low = q.unit.strip().lower()
    if low in _TIME_TO_S:
        q.normalized_value, q.normalized_unit = q.value * _TIME_TO_S[low], "s"
    elif low in _CONC_TO_PPM:
        q.normalized_value, q.normalized_unit = q.value * _CONC_TO_PPM[low], "ppm"
    elif low in _TEMP_UNITS:
        q.normalized_value, q.normalized_unit = q.value, "°C"
    return q


def normalize_record(record: SensorRecord) -> SensorRecord:
    for sample in record.samples:
        if sample.synthesis:
            sample.synthesis.temperature = normalize_quantity(sample.synthesis.temperature)
            sample.synthesis.reaction_time = normalize_quantity(sample.synthesis.reaction_time)
        if sample.testing_conditions:
            sample.testing_conditions.concentration = normalize_quantity(sample.testing_conditions.concentration)
            sample.testing_conditions.operating_temperature = normalize_quantity(sample.testing_conditions.operating_temperature)
            sample.testing_conditions.humidity = normalize_quantity(sample.testing_conditions.humidity)
            sample.testing_conditions.bias_voltage = normalize_quantity(sample.testing_conditions.bias_voltage)
        if sample.performance:
            p = sample.performance
            if p.sensor_response and p.sensor_response.value: p.sensor_response.value = normalize_quantity(p.sensor_response.value)
            if p.sensitivity and p.sensitivity.value: p.sensitivity.value = normalize_quantity(p.sensitivity.value)
            if p.limit_of_detection and p.limit_of_detection.value: p.limit_of_detection.value = normalize_quantity(p.limit_of_detection.value)
            for t in [p.response_time, p.recovery_time]:
                if t:
                    t.value = normalize_quantity(t.value)
                    t.concentration = normalize_quantity(t.concentration)
                    t.operating_temperature = normalize_quantity(t.operating_temperature)
    return record
