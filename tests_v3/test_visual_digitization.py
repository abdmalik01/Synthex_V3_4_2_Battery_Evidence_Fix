from __future__ import annotations

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from synthex_platform.visual.digitization.cache import DigitizationCache
from synthex_platform.visual.digitization.calibration import data_to_pixel, pixel_to_data
from synthex_platform.visual.digitization.exports import export_digitization
from synthex_platform.visual.digitization.models import AxisCalibration, DigitizationRequest, PixelBoundingBox, PlotArea, SeriesSelection
from synthex_platform.visual.digitization.pipeline import digitize_plot
from synthex_platform.visual.digitization.uncertainty import rounded_value_and_uncertainty
from synthex_platform.visual.models import VisualDocument


def _plot_png(x, ys, *, xlim=(0, 10), ylim=(0, 10), xscale="linear", yscale="linear", dpi=160):
    figure, axes = plt.subplots(figsize=(5, 4), dpi=dpi)
    colors = ["#e41a1c", "#377eb8"]
    for values, color in zip(ys, colors):
        axes.plot(x, values, color=color, linewidth=1.8, marker="o" if len(ys) == 1 else None)
    axes.set(xlim=xlim, ylim=ylim, xscale=xscale, yscale=yscale)
    figure.canvas.draw()
    width, height = figure.canvas.get_width_height()
    extent = axes.get_window_extent()
    # Matplotlib extents use a lower-left origin; PNG uses top-left.
    bbox = PixelBoundingBox(x0=extent.x0, y0=height - extent.y1, x1=extent.x1, y1=height - extent.y0)
    output = BytesIO(); figure.savefig(output, format="png", dpi=dpi); plt.close(figure)
    return output.getvalue(), bbox, width, height


def _request(bbox, width, height, *, xlim=(0, 10), ylim=(0, 10), xscale="linear", yscale="linear", state="user_confirmed", multi=False):
    xscale = "log10" if xscale == "log" else xscale
    yscale = "log10" if yscale == "log" else yscale
    return DigitizationRequest(
        source_id="src-plot", page=1, figure_id="fig-plot", plot_area=PlotArea(bbox=bbox, resolution_width=width, resolution_height=height, state=state),
        x_axis=AxisCalibration(axis="x", pixel_start=bbox.x0, pixel_end=bbox.x1, data_start=xlim[0], data_end=xlim[1], scale_type=xscale, state=state),
        y_axis=AxisCalibration(axis="y", pixel_start=bbox.y1, pixel_end=bbox.y0, data_start=ylim[0], data_end=ylim[1], scale_type=yscale, state=state),
        series=[SeriesSelection(series_id="series-red", color_rgb=(228, 26, 28), series_label="known", association_status="verified"), *([SeriesSelection(series_id="series-blue", color_rgb=(55, 126, 184), association_status="ambiguous")] if multi else [])],
        sampling_strategy="fixed_x_intervals", sample_count=40,
    )


def test_linear_recovery_provenance_sampling_and_export(tmp_path):
    x = np.linspace(0, 10, 100); expected = 0.8 * x + 1
    image, bbox, width, height = _plot_png(x, [expected])
    result = digitize_plot(image, _request(bbox, width, height))
    assert result.status == "completed" and 2 <= len(result.series[0].points) <= 40
    point = result.series[0].points[len(result.series[0].points) // 2]
    assert point.estimated is True and point.origin == "figure_digitized"
    assert point.evidence_strength == "estimated_digitized" and point.admission_status == "not_submitted"
    assert abs(point.y - (0.8 * point.x + 1)) < 0.25
    exported = export_digitization(tmp_path, result, image)
    assert {item.name for item in exported.iterdir()} >= {"data.csv", "data.json", "digitization_spec.json", "provenance.json", "preview.png"}
    assert rounded_value_and_uncertainty(113.427138, 2.0) == (113.0, 2.0)


def test_log_reversed_round_trip_and_sidecar_compatibility():
    axis = AxisCalibration(axis="x", pixel_start=300, pixel_end=100, data_start=1, data_end=1000, scale_type="log10", state="verified")
    assert pixel_to_data(data_to_pixel(10, axis), axis) == pytest.approx(10)
    old = VisualDocument(source_id="src-old", source_checksum="abc")
    payload = old.model_dump(); payload.pop("digitizations")
    assert VisualDocument.model_validate(payload).digitizations == []


def test_multi_series_and_rejection_policies(tmp_path):
    x = np.linspace(0, 10, 100)
    image, bbox, width, height = _plot_png(x, [x * 0.7 + 1, 9 - x * 0.5])
    result = digitize_plot(image, _request(bbox, width, height, multi=True))
    assert result.status == "completed" and all(series.points for series in result.series)
    assert result.series[1].series_label is None and result.series[1].association_status == "ambiguous"
    rejected = digitize_plot(image, _request(bbox, width, height, state="automatically_inferred"))
    assert rejected.status == "rejected" and "calibration_not_user_confirmed" in rejected.rejection_reasons
    unsupported_request = _request(bbox, width, height).model_copy(update={"requested_geometry": "dual_y"})
    assert "unsupported_geometry:dual_y" in digitize_plot(image, unsupported_request).rejection_reasons
    three_d = _request(bbox, width, height).model_copy(update={"requested_geometry": "three_d"})
    assert "unsupported_geometry:three_d" in digitize_plot(image, three_d).rejection_reasons
    low_resolution = _request(bbox, 40, 40)
    assert "plot_resolution_too_low" in digitize_plot(image, low_resolution).rejection_reasons
    duplicate = _request(bbox, width, height, multi=True).model_copy(update={"series": [_request(bbox, width, height).series[0], SeriesSelection(series_id="series-same", color_rgb=(228, 26, 28))]})
    assert "series_colors_not_separable" in digitize_plot(image, duplicate).rejection_reasons
    cache = DigitizationCache(tmp_path / "cache")
    base = _request(bbox, width, height)
    changed = base.model_copy(update={"x_axis": base.x_axis.model_copy(update={"data_end": 11})})
    assert cache.key("checksum", base) != cache.key("checksum", changed)


@pytest.mark.parametrize(
    ("name", "x", "values", "xlim", "ylim", "xscale", "yscale", "limit"),
    [
        ("linear", np.linspace(0, 10, 100), lambda x: 0.8 * x + 1, (0, 10), (0, 10), "linear", "linear", 0.30),
        ("reversed", np.linspace(0, 10, 100), lambda x: 0.5 * x + 2, (10, 0), (8, 0), "linear", "linear", 0.30),
        ("log", np.geomspace(1, 1000, 150), lambda x: np.sqrt(x), (1, 1000), (1, 40), "log", "log", 1.0),
        ("cycling", np.linspace(0, 200, 180), lambda x: 145 - 0.12 * x, (0, 200), (100, 160), "linear", "linear", 1.0),
        ("nyquist", np.linspace(0, 10, 150), lambda x: np.sqrt(np.clip(25 - (x - 5) ** 2, 0, None)), (0, 10), (0, 6), "linear", "linear", 0.25),
        ("spectrum", np.linspace(0, 1000, 240), lambda x: 2 + 6 * np.exp(-((x - 400) / 90) ** 2), (0, 1000), (0, 10), "linear", "linear", 0.25),
    ],
)
def test_controlled_scientific_plot_benchmark(name, x, values, xlim, ylim, xscale, yscale, limit):
    """Ground-truth regression: recovered estimates must retain practical accuracy."""
    expected = values(x)
    image, bbox, width, height = _plot_png(x, [expected], xlim=xlim, ylim=ylim, xscale=xscale, yscale=yscale)
    result = digitize_plot(image, _request(bbox, width, height, xlim=xlim, ylim=ylim, xscale=xscale, yscale=yscale))
    recovered = result.series[0].points
    actual = np.asarray([values(point.x) for point in recovered])
    observed = np.asarray([point.y for point in recovered])
    mae = float(np.mean(np.abs(actual - observed)))
    recovery_rate = len(recovered) / 40
    assert result.status == "completed", name
    assert mae < limit, (name, mae)
    assert recovery_rate >= 0.8, (name, recovery_rate)
