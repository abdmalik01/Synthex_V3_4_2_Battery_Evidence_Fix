from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import CalculationRecord, DomainPayload, Evidence, ExperimentRecord, MaterialEntity, Measurement, SourceRecord
from synthex_platform.visual.analytics.exports import comparison_frame, export_visualization
from synthex_platform.visual.analytics.models import AnalyticMeasurementRow, AnalyticQuery
from synthex_platform.visual.analytics.projection import project_archives
from synthex_platform.visual.analytics.render import VisualizationRenderer, observed_rectangular_grid
from synthex_platform.visual.analytics.specs import build_visualization_spec, chart_field_options, surface_coverage


def _archive(
    index: int,
    temp: float,
    capacity: float,
    unit: str = "mAh/g",
    *,
    cycle: int = 1,
    c_rate: str | None = None,
    point_temperature: str | None = None,
):
    source_id, material_id, experiment_id = f"src-00{index}", f"mat-00{index}", f"exp-00{index}"
    evidence = Evidence(source_id=source_id, page=2, source_type="table", text_snippet=f"{capacity} {unit}", table_id=f"tbl-{index}")
    point_conditions = {"cycle": cycle}
    if c_rate is not None:
        point_conditions["C_rate"] = c_rate
    if point_temperature is not None:
        point_conditions["temperature"] = point_temperature
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id=f"arc-00{index}", domain="batteries"),
        sources=[SourceRecord(source_id=source_id, title=f"Paper {index}")],
        materials=[MaterialEntity(material_id=material_id, name=f"Material {chr(64 + index)}")],
        experiments=[ExperimentRecord(
            experiment_id=experiment_id,
            experiment_type="galvanostatic cycling",
            material_ids=[material_id],
            conditions=[
                Measurement(property="temperature", raw_value=f"{temp} °C", value=temp, unit="°C"),
                Measurement(property="cycle", raw_value=str(cycle), value=cycle, unit="cycle"),
            ],
            outputs=[Measurement(
                property="specific_capacity",
                raw_value=f"{capacity} {unit}",
                value=capacity,
                unit=unit,
                normalized_value=capacity,
                normalized_unit=unit,
                conditions=point_conditions,
                evidence=[evidence],
            )],
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


def test_projection_preserves_point_specific_battery_conditions_as_numeric_dimensions():
    row = project_archives([
        _archive(1, 25, 150, c_rate="C/10", point_temperature="35 °C", cycle=25)
    ])[0]
    assert row.conditions["C_rate"] == 0.1
    assert row.conditions["C_rate_raw"] == "C/10"
    assert row.conditions["C_rate_unit"] == "C"
    assert row.conditions["temperature"] == 35.0
    assert row.conditions["temperature_raw"] == "35 °C"
    assert row.conditions["temperature_unit"] == "°C"
    assert row.conditions["cycle"] == 25.0


def test_chart_field_options_are_data_aware_for_battery_rows():
    rows = project_archives([
        _archive(1, 25, 150, c_rate="0.1C"),
        _archive(2, 25, 140, c_rate="1C"),
    ])
    line = chart_field_options(rows, "line")
    assert "conditions.C_rate" in line["x"]
    assert "conditions.temperature" in line["x"]
    assert "material_label" not in line["x"]
    assert line["y"][0] == "value"
    bar = chart_field_options(rows, "bar")
    assert "material_label" in bar["x"]


def test_comparison_exports_specs_and_rendered_demonstration(tmp_path):
    rows = project_archives([
        _archive(1, 25, 90, c_rate="0.1C"),
        _archive(2, 25, 110, c_rate="0.5C"),
        _archive(3, 25, 121, c_rate="1C"),
    ])
    frame = comparison_frame(rows)
    assert {"material", "archive_id", "source_id", "evidence_references", "condition_C_rate"} <= set(frame.columns)
    query = AnalyticQuery(property_name="specific_capacity")
    scatter = build_visualization_spec(
        rows,
        "scatter",
        "Capacity versus C-rate",
        x_field="conditions.C_rate",
        y_field="value",
        query=query,
    )
    same = build_visualization_spec(
        rows,
        "scatter",
        "Capacity versus C-rate",
        x_field="conditions.C_rate",
        y_field="value",
        query=query,
    )
    assert scatter.eligible and scatter.visualization_id == same.visualization_id
    target = export_visualization(tmp_path, scatter, rows)
    assert {"spec.json", "data.csv", "data.json", "provenance.json", "chart.png"} <= {path.name for path in target.iterdir()}


def _surface_rows():
    return project_archives([
        _archive(1, 25, 155, c_rate="0.1C"),
        _archive(2, 25, 130, c_rate="1C"),
        _archive(3, 45, 145, c_rate="0.1C"),
        _archive(4, 45, 118, c_rate="1C"),
    ])


def _resistance_grid_rows():
    return [
        AnalyticMeasurementRow(
            archive_id=f"arc-{soc}-{temperature}",
            source_id="src-nmc",
            experiment_id=f"exp-{soc}-{temperature}",
            modality="experimental",
            property_name="internal_resistance",
            value=10.0 + soc / 10.0 + temperature / 100.0,
            unit="mΩ",
            normalized_unit="mΩ",
            conditions={
                "temperature": float(temperature),
                "temperature_unit": "°C",
                "state_of_charge": float(soc),
                "state_of_charge_unit": "%",
            },
        )
        for soc in (20, 80)
        for temperature in (0, 25, 50)
    ]


def test_surface_spec_generates_human_readable_title_axis_and_colorbar_labels():
    rows = _resistance_grid_rows()
    spec = build_visualization_spec(
        rows,
        "heatmap",
        x_field="conditions.temperature",
        y_field="conditions.state_of_charge",
        z_field="value",
    )

    assert spec.title == "Internal Resistance vs Temperature and State of Charge"
    assert spec.x_label == "Temperature"
    assert spec.y_label == "State of Charge"
    assert spec.z_label == "Internal Resistance"
    assert spec.units == {"x": "°C", "y": "%", "z": "mΩ"}

    figure, axis = plt.subplots()
    VisualizationRenderer()._cartesian(axis, spec, rows)
    assert axis.get_xlabel() == "Temperature (°C)"
    assert axis.get_ylabel() == "State of Charge (%)"
    assert figure.axes[1].get_ylabel() == "Internal Resistance (mΩ)"
    plt.close(figure)


def test_complete_heatmap_grid_uses_only_observed_cells_without_artificial_values():
    rows = _resistance_grid_rows()
    coverage = surface_coverage(
        rows,
        "conditions.temperature",
        "conditions.state_of_charge",
        "value",
    )
    assert coverage["complete_rectangular_grid"] is True
    assert coverage["duplicate_coordinates"] == 0

    grid = observed_rectangular_grid(
        rows,
        "conditions.temperature",
        "conditions.state_of_charge",
        "value",
    )
    assert grid is not None
    x_values, y_values, z_values = grid
    assert x_values == [0.0, 25.0, 50.0]
    assert y_values == [20.0, 80.0]
    assert z_values.shape == (2, 3)
    assert set(z_values.ravel()) == {row.value for row in rows}
    assert observed_rectangular_grid(
        rows[:-1],
        "conditions.temperature",
        "conditions.state_of_charge",
        "value",
    ) is None

    spec = build_visualization_spec(
        rows,
        "heatmap",
        x_field="conditions.temperature",
        y_field="conditions.state_of_charge",
        z_field="value",
    )
    figure, axis = plt.subplots()
    VisualizationRenderer()._cartesian(axis, spec, rows)
    assert any(collection.__class__.__name__ == "QuadMesh" for collection in axis.collections)
    plt.close(figure)


def test_contour_measured_point_overlay_is_presentation_only_and_does_not_mutate_rows():
    rows = _resistance_grid_rows()
    before = [row.model_dump(mode="json") for row in rows]
    spec = build_visualization_spec(
        rows,
        "contour",
        x_field="conditions.temperature",
        y_field="conditions.state_of_charge",
        z_field="value",
        show_measured_points=True,
    )

    assert spec.show_measured_points is True
    assert spec.rendering_warnings == [
        "Filled contours interpolate between source-reported measurements for visualization only."
    ]
    assert VisualizationRenderer().render_png(spec, rows)
    assert [row.model_dump(mode="json") for row in rows] == before


def test_line_scatter_heatmap_and_contour_use_correct_axis_contracts():
    rows = _surface_rows()
    assert build_visualization_spec(
        rows, "bar", "Capacity", x_field="material_label", y_field="value"
    ).eligible
    assert build_visualization_spec(
        rows, "line", "Capacity", x_field="conditions.C_rate", y_field="value"
    ).eligible
    assert build_visualization_spec(
        rows, "scatter", "Capacity", x_field="conditions.temperature", y_field="value"
    ).eligible

    heatmap = build_visualization_spec(
        rows,
        "heatmap",
        "Capacity map",
        x_field="conditions.C_rate",
        y_field="conditions.temperature",
        z_field="value",
    )
    assert heatmap.eligible and heatmap.z_field == "value"
    assert VisualizationRenderer().render_png(heatmap, rows)

    contour = build_visualization_spec(
        rows,
        "contour",
        "Capacity contour",
        x_field="conditions.C_rate",
        y_field="conditions.temperature",
        z_field="value",
    )
    assert contour.eligible
    assert contour.rendering_warnings
    assert VisualizationRenderer().render_png(contour, rows)


def test_heatmap_and_contour_reject_missing_or_duplicate_axes():
    rows = _surface_rows()
    missing_z = build_visualization_spec(
        rows,
        "heatmap",
        "No Z",
        x_field="conditions.C_rate",
        y_field="conditions.temperature",
    )
    assert not missing_z.eligible and missing_z.reason == "missing_z_axis"
    duplicate = build_visualization_spec(
        rows,
        "contour",
        "Duplicate",
        x_field="conditions.C_rate",
        y_field="value",
        z_field="value",
    )
    assert not duplicate.eligible and duplicate.reason == "axes_must_be_distinct"


def test_chart_guardrails_and_modality_distinction():
    compatible = project_archives([
        _archive(1, 600, 90, c_rate="0.1C"),
        _archive(2, 650, 110, c_rate="0.5C"),
        _archive(3, 700, 121, c_rate="1C"),
    ])
    assert build_visualization_spec(compatible, "radar", "Unsafe", radar_fields=["value", "conditions.temperature", "conditions.cycle"]).reason == "radar_requires_explicit_normalization_policy"

    incompatible = project_archives([
        _archive(1, 600, 90, c_rate="0.1C"),
        _archive(2, 650, 110, "%", c_rate="1C"),
    ])
    assert build_visualization_spec(
        incompatible,
        "scatter",
        "Mixed",
        x_field="conditions.C_rate",
        y_field="value",
    ).reason == "incompatible_value_units"

    archive = _archive(4, 720, 130)
    archive.calculations.append(CalculationRecord(
        calculation_id="calc-004",
        calculation_type="dft",
        material_ids=["mat-004"],
        outputs=[Measurement(property="band_gap", raw_value="2.1 eV", value=2.1, unit="eV")],
    ))
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
