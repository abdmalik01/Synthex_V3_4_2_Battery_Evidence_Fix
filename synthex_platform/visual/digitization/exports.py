"""Explicit exports for one inspected digitization; never archive output."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw

from synthex_platform.version import __version__

from .models import DigitizationResult
from .uncertainty import rounded_value_and_uncertainty


def export_digitization(output_directory: str | Path, result: DigitizationResult, source_image_png: bytes) -> Path:
    target = Path(output_directory) / "visual" / result.source_id / "digitizations" / result.digitization_id
    target.mkdir(parents=True, exist_ok=True)
    rows = [point for series in result.series for point in series.points]
    with (target / "data.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["series_id", "x", "y", "uncertainty_x", "uncertainty_y", "raw_pixel_x", "raw_pixel_y", "estimated", "origin", "evidence_strength"])
        writer.writeheader()
        exported_rows = []
        for point in rows:
            x, uncertainty_x = rounded_value_and_uncertainty(point.x, point.uncertainty_x)
            y, uncertainty_y = rounded_value_and_uncertainty(point.y, point.uncertainty_y)
            row = {"series_id": point.series_id, "x": x, "y": y, "uncertainty_x": uncertainty_x, "uncertainty_y": uncertainty_y, "raw_pixel_x": point.raw_pixel_x, "raw_pixel_y": point.raw_pixel_y, "estimated": True, "origin": "figure_digitized", "evidence_strength": "estimated_digitized"}
            writer.writerow(row)
            exported_rows.append(row)
    (target / "data.json").write_text(json.dumps(exported_rows, indent=2), encoding="utf-8")
    (target / "digitization_spec.json").write_text(json.dumps({"digitization_id": result.digitization_id, "plot_area": result.plot_area.model_dump(mode="json"), "calibration": {key: value.model_dump(mode="json") for key, value in result.calibration.items()}, "algorithm": result.algorithm, "digitizer_version": result.digitizer_version}, indent=2), encoding="utf-8")
    provenance = {"synthex_version": __version__, "source_id": result.source_id, "page": result.page, "figure_id": result.figure_id, "panel": result.panel, "source_image_checksum": result.source_image_checksum, "provenance": result.provenance, "uncertainty": result.uncertainty.model_dump(mode="json") if result.uncertainty else None, "warnings": result.warnings, "rejection_reasons": result.rejection_reasons}
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    image = Image.open(__import__("io").BytesIO(source_image_png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for point in rows:
        radius = 2
        draw.ellipse((point.raw_pixel_x - radius, point.raw_pixel_y - radius, point.raw_pixel_x + radius, point.raw_pixel_y + radius), outline=(255, 0, 255), width=1)
    image.save(target / "preview.png")
    return target
