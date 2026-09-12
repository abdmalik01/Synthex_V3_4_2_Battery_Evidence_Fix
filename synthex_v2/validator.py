from __future__ import annotations
from .models import SensorRecord


def validate_semantics(record: SensorRecord) -> list[str]:
    warnings = []
    for i, sample in enumerate(record.samples, start=1):
        label = sample.sample_id or sample.material or f"sample {i}"
        p = sample.performance
        if not p: continue
        if p.sensitivity and p.sensitivity.value and not p.sensitivity.evidence:
            warnings.append(f"{label}: sensitivity has a value but no evidence object.")
        if p.response_time and p.response_time.value and not p.response_time.criterion:
            warnings.append(f"{label}: response-time criterion (t90/t95/etc.) was not reported or extracted.")
        if p.recovery_time and p.recovery_time.value and not p.recovery_time.criterion:
            warnings.append(f"{label}: recovery-time criterion (t90/t95/etc.) was not reported or extracted.")
        if p.selectivity and p.selectivity.entries:
            for e in p.selectivity.entries:
                if e.selectivity_ratio is None and e.target_response is None and e.interferent_response is None:
                    warnings.append(f"{label}: selectivity entry for {e.interferent or 'an interferent'} is qualitative only.")
    return warnings
