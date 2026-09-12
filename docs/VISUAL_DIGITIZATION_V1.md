# Visual Intelligence: digitization V1

Digitization V1 recovers **estimated** values from a researcher-confirmed 2D plot calibration. It does not extract author-reported values and never writes canonical archive records.

## Supported subset

Linear or log10 Cartesian axes (including reversed directions); a selected panel; clearly separable coloured lines or scatter/marker series; cycling, charge/discharge, CV, Tafel/polarization, Nyquist, and suitable spectra/DOS plots. Multiple series require an explicit colour selection. A legend label is null unless it is verified or deterministically associated.

## Rejected subset

3D, ternary, polar, broken-axis, dual-y, heatmap, contour, microscopy, schematic, unbounded/low-resolution plot areas, ambiguous calibration, severely overlapping series, and ambiguous grayscale multi-series plots are rejected with explicit reasons.

## Calibration and uncertainty

The user confirms a plot rectangle and two pixel/data references for each axis. Only `verified` and `user_confirmed` calibrations can complete production digitization. `automatically_inferred` calibrations can support preview diagnostics only.

Pixels are transformed deterministically by linear interpolation or log10 interpolation. Each point retains raw pixel coordinates and x/y uncertainty derived from at least one pixel, calibration residual, line thickness, marker radius, crop uncertainty, and overlap warnings. Consumer-facing values must be rounded to the uncertainty scale; raw internal floats remain available for audit.

## Provenance and exports

Each point is permanently `origin=figure_digitized`, `estimated=true`, `evidence_strength=estimated_digitized`, and `admission_status=not_submitted`. It references source/page/figure/panel and cannot pass through the visual-to-core bridge.

Explicit exports contain `data.csv`, `data.json`, `digitization_spec.json`, `provenance.json`, and `preview.png`, with sampled points overlaid on the rendered source. Cache identity includes image checksum, figure/panel, calibration, options, and digitizer version, so calibration changes invalidate cache results.

## Limitations

V1 uses NumPy and Pillow colour masks rather than OpenCV. It intentionally does not attempt general grayscale separation, automatic authoritative tick reading, or a WebPlotDigitizer-equivalent vision system. Controlled synthetic benchmark plots, not ungrounded real-paper curves, are its quantitative acceptance tests.
