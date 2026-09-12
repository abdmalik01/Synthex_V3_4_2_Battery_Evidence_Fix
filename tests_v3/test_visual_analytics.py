from __future__ import annotations

from pathlib import Path

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import CalculationRecord, DomainPayload, Evidence, ExperimentRecord, MaterialEntity, Measurement, SourceRecord
from synthex_platform.visual.analytics.exports import comparison_frame, export_visualization
from synthex_platform.visual.analytics.models import AnalyticQuery
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.specs import build_visualization_spec


def _archive(index: int, temp: float, capacity: float, unit: str = "mAh/g"):
    source_id, material_id, experiment_id = f"src-00{index}", f"mat-00{index}", f"exp-00{index}"
    evidence = Evidence(source_id=source_id, page=2, source_type="table", text_snippet=f"{capacity} {unit}", table_id=f"tbl-{index}")
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id=f"arc-00{index}", domain="batteries"),
        sources=[SourceRecord(source_id=source_id, title=f"Paper {index}")],
        materials=[MaterialEntity(material_id=material_id, name=f"Material {chr(64 + index)}")],
        experiments=[ExperimentRecord(
            experiment_id=experiment_id, experiment_type="galvanostatic cycling", material_ids=[material_id],
            conditions=[Measurement(property="temperature", raw_value=f"{temp} °C", value=temp, unit="°C"), Measurement(property="cycle", raw_value="1", value=1, unit="cycle")],
            outputs=[Measurement(property="specific_capacity", raw_value=f"{capacity} {unit}", value=capacity, unit=unit, normalized_value=capacity, normalized_unit=unit, evidence=[evidence])],
        )],
        domain_payloads=[DomainPayload(domain="batteries", schema_version="1", values={"admissibility": {"quarantine": [{"value": 999}]}})],
    )


def test_projection_filters_multi_source_traceability_and_noncanonical_exclusion():
    archives = [_archive(1, 600, 90), _archive(2, 650, 110), _archive(3, 700, 121)]
    rows = project_archives(archives)
    assert len(rows) == 3
    assert {row.source_id for row in rows} == {"src-001", "src-002", "src-003"}
    assert all(row.value != 999 and row.experiment_id and row.evidence_references for row in rows)
    filtered = project_archives(archives, AnalyticQuery(property_name="specific_capacity", temperature_min=640, value_min=100))
    assert [row.value for row in filtered] == [110.0, 121.0]


def test_comparison_exports_specs_and_rendered_demonstration(tmp_path):
    rows = project_archives([_archive(1, 600, 90), _archive(2, 650, 110), _archive(3, 700, 121)])
    frame = comparison_frame(rows)
    assert {"material", "archive_id", "source_id", "evidence_references"} <= set(frame.columns)
    query = AnalyticQuery(property_name="specific_capacity")
    scatter = build_visualization_spec(rows, "scatter", "Capacity versus temperature", x_field="conditions.temperature", y_field="value", query=query)
    same = build_visualization_spec(rows, "scatter", "Capacity versus temperature", x_field="conditions.temperature", y_field="value", query=query)
    assert scatter.eligible and scatter.visualization_id == same.visualization_id
    target = export_visualization(tmp_path, scatter, rows)
    assert {"spec.json", "data.csv", "data.json", "provenance.json", "chart.png"} <= {path.name for path in target.iterdir()}


def test_chart_guardrails_and_modality_distinction():
    compatible = project_archives([_archive(1, 600, 90), _archive(2, 650, 110), _archive(3, 700, 121)])
    assert build_visualization_spec(compatible, "bar", "Capacity", x_field="material_label", y_field="value").eligible
    assert build_visualization_spec(compatible, "line", "Capacity", x_field="conditions.temperature", y_field="value").eligible
    assert build_visualization_spec(compatible, "heatmap", "Capacity", x_field="conditions.temperature", y_field="value").eligible
    assert build_visualization_spec(compatible[:3], "contour", "Sparse", x_field="conditions.temperature", y_field="value").reason == "insufficient_data_density"
    assert build_visualization_spec(compatible, "radar", "Unsafe", radar_fields=["value", "conditions.temperature", "conditions.cycle"]).reason == "radar_requires_explicit_normalization_policy"

    incompatible = project_archives([_archive(1, 600, 90), _archive(2, 650, 110, "%")])
    assert build_visualization_spec(incompatible, "scatter", "Mixed", x_field="conditions.temperature", y_field="value").reason == "incompatible_y_units"

    archive = _archive(4, 720, 130)
    archive.calculations.append(CalculationRecord(calculation_id="calc-004", calculation_type="dft", material_ids=["mat-004"], outputs=[Measurement(property="band_gap", raw_value="2.1 eV", value=2.1, unit="eV")]))
    rows = project_archives([archive])
    assert {row.modality for row in rows} == {"experimental", "computational"}
    assert not any(row.value is None and row.raw_value is None for row in rows)


def test_missing_values_remain_missing_and_do_not_make_a_chart_eligible():
    archive = _archive(5, 750, 140)
    archive.experiments[0].outputs.append(Measurement(property="specific_capacity", raw_value="not reported", value=None, unit="mAh/g"))
    rows = project_archives([archive])
    missing = next(row for row in rows if row.raw_value == "not reported")
    assert missing.value is None
    spec = build_visualization_spec([missing], "scatter", "Missing value", x_field="conditions.temperature", y_field="value")
    assert not spec.eligible and spec.reason == "missing_numeric_axes"
