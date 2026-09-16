"""Explicit, caller-controlled visualization artifacts and traceability exports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from synthex_platform.version import __version__
from .models import AnalyticMeasurementRow, VisualizationSpec
from .render import VisualizationRenderer


def comparison_frame(rows: list[AnalyticMeasurementRow]) -> pd.DataFrame:
    """Friendly analysis columns plus traceability and flattened condition dimensions."""
    condition_keys = sorted({
        key
        for row in rows
        for key in row.conditions
        if not key.endswith("_raw") and not key.endswith("_unit")
    }, key=str.casefold)
    records = []
    for row in rows:
        record = {
            "material": row.material_label,
            "property": row.property_name,
            "value": row.value,
            "raw_value": row.raw_value,
            "unit": row.normalized_unit or row.unit,
            "modality": row.modality,
            "method": row.method,
        }
        for key in condition_keys:
            record[f"condition_{key}"] = row.conditions.get(key)
            unit = row.conditions.get(f"{key}_unit")
            if unit not in (None, ""):
                record[f"condition_{key}_unit"] = unit
        record.update({
            "conditions": json.dumps(row.conditions, ensure_ascii=False, sort_keys=True),
            "archive_id": row.archive_id,
            "source_id": row.source_id,
            "material_id": row.material_id,
            "experiment_id": row.experiment_id,
            "calculation_id": row.calculation_id,
            "evidence_references": json.dumps(row.evidence_references, ensure_ascii=False, sort_keys=True),
        })
        records.append(record)
    return pd.DataFrame(records)


def export_visualization(
    output_directory: str | Path, spec: VisualizationSpec, rows: list[AnalyticMeasurementRow], *, render_chart: bool = True,
) -> Path:
    """Create files only on explicit caller request under a caller-owned directory."""
    target = Path(output_directory) / "visualizations" / spec.visualization_id
    target.mkdir(parents=True, exist_ok=True)
    metadata = {
        "generated_by_synthex": True,
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "synthex_version": __version__,
        "visualization_specification": spec.model_dump(mode="json"),
        "archive_ids": sorted({row.archive_id for row in rows}),
        "source_ids": sorted({row.source_id for row in rows if row.source_id}),
    }
    (target / "spec.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    frame = comparison_frame(rows)
    frame.to_csv(target / "data.csv", index=False)
    (target / "data.json").write_text(json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "provenance.json").write_text(json.dumps(spec.provenance_references, ensure_ascii=False, indent=2), encoding="utf-8")
    if render_chart and spec.eligible:
        (target / "chart.png").write_bytes(VisualizationRenderer().render_png(spec, rows))
    return target