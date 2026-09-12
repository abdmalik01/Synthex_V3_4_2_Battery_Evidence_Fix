# Visual Intelligence V1 — COMPLETE

## Architecture

Visual Intelligence is an additive cross-domain layer:

```text
PDF / rendered figure
→ native extraction or explicit OCR
→ table / figure / digitization sidecar objects
→ researcher review, visualization, or explicit export
```

It does not automatically create canonical `Measurement`, `Experiment`, `Calculation`, or `Material` records. Batteries V1 is frozen and its schemas and admission rules are unchanged.

## Completed stages

1. Native PDF text and table extraction with raw and conservative normalized representations.
2. Visual provenance, typed `VisualDocument` objects, deterministic sidecars, and non-mutating evidence bridges.
3. Figure candidate discovery, crops, panels, axes, legends, and optional bounded semantic understanding.
4. Canonical-archive projections into guarded generated tables and charts.
5. Tesseract OCR fallback for insufficient native text, with raw and normalized text separate.
6. User-confirmed calibrated graph digitization with deterministic pixel-to-coordinate conversion and uncertainty.

## Supported capabilities

- Native tables, source/page/cell provenance, figures, panels, captions, axes, and legends.
- Local OCR of insufficient pages, marked `origin="ocr_extracted"`.
- Exported comparison tables and charts derived from canonical records.
- Calibrated selected-panel Cartesian plots with linear or log10 axes, reversed axes, and clearly distinct coloured line/scatter series. Bounded sampling, calibration-sensitive cache invalidation, CSV/JSON/spec/provenance/preview exports, and raw pixel-space audit data are included.

## Provenance and scientific guarantees

Origins include `text_reported`, `table_reported`, `table_footnote`, `figure_caption`, `figure_annotation`, `figure_digitized`, `ocr_extracted`, `supplementary_material`, and `web_enriched`.

OCR is explicit rather than native text. Every digitized point has `origin="figure_digitized"`, `estimated=true`, `evidence_strength="estimated_digitized"`, and `admission_status="not_submitted"`. Calibration state, uncertainty, warnings, rejection reasons, source checksum, figure/panel reference, and raw pixel coordinates are retained. Visual and digitized outputs remain outside canonical admission by default.

## Deliberate V1 limits

The digitizer rejects 3D, ternary, polar, dual-y, broken-axis, heatmap/contour, microscopy, schematic, low-resolution, uncertain-calibration, and ambiguous/overlapping-series cases. Automatic calibration is diagnostic only; production completion requires verified or user-confirmed calibration. General grayscale separation and OpenCV-based computer vision are deferred.

## Tests and dependencies

The repository collects 93 tests. Focused Visual Intelligence Stages 1–6 tests pass (33 tests), including controlled synthetic linear, reversed, log, cycling-like, Nyquist-like, and spectral recovery benchmarks plus explicit rejection tests.

V1 uses PyMuPDF, PyPDF, Pydantic, NumPy, Pillow, Matplotlib, and optional local Tesseract. No OpenCV, external digitization service, or Gemini numerical extraction is required.

## Future V2 backlog

- Confirmed grayscale and overlapping-series workflows.
- More robust plot/axis/marker detection if controlled benchmarks justify OpenCV.
- Richer multi-panel selection and legend association.
- Human review queue and a separately governed policy for any future canonical use of digitized estimates.
