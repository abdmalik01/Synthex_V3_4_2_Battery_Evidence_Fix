"""Safe pipeline for selected-color, calibrated Cartesian 2D digitization."""

from __future__ import annotations

from hashlib import sha256

from synthex_platform.core.identifiers import stable_id
from synthex_platform.visual.models import VisualProvenance

from .calibration import calibration_is_production_ready
from .image_processing import crop_plot
from .models import DigitizationRequest, DigitizationResult, DigitizedPoint, DigitizedSeries
from .series import extract_selected_series
from .uncertainty import estimate_uncertainty


DIGITIZER_VERSION = "digitization_v1"
_UNSUPPORTED = {"dual_y", "broken_axis", "polar", "ternary", "three_d", "heatmap", "contour", "image", "schematic"}


def _result(request: DigitizationRequest, checksum: str, status: str, *, reasons=None, series=None, uncertainty=None, warnings=None) -> DigitizationResult:
    provenance = VisualProvenance(origin="figure_digitized", source_id=request.source_id, page=request.page, object_id=request.figure_id, object_type="figure", panel=request.panel, parser_or_method="numpy_pillow_colored_curve_v1", verification_status="candidate").model_dump(mode="json", exclude_none=True)
    digest = stable_id("dig", checksum, request.figure_id, request.panel, request.plot_area.model_dump(mode="json"), request.x_axis.model_dump(mode="json"), request.y_axis.model_dump(mode="json"), [item.model_dump(mode="json") for item in request.series], request.sampling_strategy, request.sample_count, request.options)
    return DigitizationResult(digitization_id=digest, source_id=request.source_id, page=request.page, figure_id=request.figure_id, panel=request.panel, plot_area=request.plot_area, source_image_checksum=checksum, calibration={"x": request.x_axis, "y": request.y_axis}, series=series or [], uncertainty=uncertainty, status=status, rejection_reasons=reasons or [], warnings=warnings or [], provenance=provenance)


def digitize_plot(image_png: bytes, request: DigitizationRequest) -> DigitizationResult:
    """Digitize only explicitly calibrated Cartesian plots; never admits archive data."""
    checksum = sha256(image_png).hexdigest()
    reasons = []
    if request.requested_geometry in _UNSUPPORTED:
        reasons.append(f"unsupported_geometry:{request.requested_geometry}")
    if request.plot_area.resolution_width < 80 or request.plot_area.resolution_height < 80:
        reasons.append("plot_resolution_too_low")
    states = {request.x_axis.state, request.y_axis.state, request.plot_area.state}
    if {"ambiguous", "failed"} & states:
        reasons.append("calibration_ambiguous_or_failed")
    ready = calibration_is_production_ready(request.x_axis) and calibration_is_production_ready(request.y_axis) and request.plot_area.state in {"verified", "user_confirmed"}
    if not ready and not request.diagnostic_mode:
        reasons.append("calibration_not_user_confirmed")
    if not request.series:
        reasons.append("no_explicit_color_series_selected")
    colors = [series.color_rgb for series in request.series]
    if any(color is None for color in colors):
        reasons.append("series_color_selection_required")
    defined_colors = [color for color in colors if color is not None]
    if len(set(defined_colors)) != len(defined_colors):
        reasons.append("series_colors_not_separable")
    grayscale = [color for color in defined_colors if max(color) - min(color) < 25]
    if len(request.series) > 1 and grayscale:
        reasons.append("ambiguous_grayscale_multi_series")
    if len(request.series) == 1 and grayscale and not request.options.get("user_selected_grayscale"):
        reasons.append("grayscale_series_requires_user_selected_target")
    if reasons:
        return _result(request, checksum, "rejected", reasons=reasons)
    try:
        plot = crop_plot(image_png, request.plot_area)
    except ValueError as error:
        return _result(request, checksum, "rejected", reasons=["plot_area_invalid", str(error)])
    uncertainty = estimate_uncertainty(request.x_axis, request.y_axis, line_thickness_px=float(request.options.get("line_thickness_px", 1.0)), marker_radius_px=float(request.options.get("marker_radius_px", 0.0)), crop_uncertainty_px=float(request.options.get("crop_uncertainty_px", 0.0)))
    if uncertainty.pixel_y > 8 or uncertainty.pixel_x > 8:
        return _result(request, checksum, "rejected", reasons=["line_or_calibration_uncertainty_too_high"], uncertainty=uncertainty)
    output = []
    for selected in request.series:
        recovered = extract_selected_series(plot, selected, request.x_axis, request.y_axis, pixel_origin=(request.plot_area.bbox.x0, request.plot_area.bbox.y0), strategy=request.sampling_strategy, sample_count=request.sample_count, tolerance=float(request.options.get("color_tolerance", 60.0)))
        if not recovered:
            output.append(DigitizedSeries(series_id=selected.series_id, series_label=selected.series_label, color_rgb=selected.color_rgb, association_status=selected.association_status, warnings=["no_confident_pixels_recovered"]))
            continue
        confidence = max(0.2, min(0.95, 1 - uncertainty.pixel_y / 12))
        points = [DigitizedPoint(x=x, y=y, raw_pixel_x=px, raw_pixel_y=py, figure_id=request.figure_id, panel=request.panel, series_id=selected.series_id, digitization_method="selected_rgb_median_trace_v1", digitizer_version=DIGITIZER_VERSION, uncertainty_x=uncertainty.x, uncertainty_y=uncertainty.y, confidence=confidence, quality_status="warning" if selected.association_status == "ambiguous" else "accepted") for x, y, px, py in recovered]
        output.append(DigitizedSeries(series_id=selected.series_id, series_label=selected.series_label, color_rgb=selected.color_rgb, association_status=selected.association_status, points=points))
    if not any(item.points for item in output):
        return _result(request, checksum, "rejected", reasons=["no_selected_series_recovered"], series=output, uncertainty=uncertainty)
    return _result(request, checksum, "diagnostic" if not ready else "completed", series=output, uncertainty=uncertainty)
