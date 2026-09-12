"""Deterministic cache identity for a calibrated digitization request."""

from __future__ import annotations

from pathlib import Path

from synthex_platform.core.identifiers import stable_id

from .models import DigitizationRequest, DigitizationResult


class DigitizationCache:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def key(self, source_image_checksum: str, request: DigitizationRequest, digitizer_version: str = "digitization_v1") -> str:
        return stable_id("digcache", source_image_checksum, request.figure_id, request.panel, request.plot_area.model_dump(mode="json"), request.x_axis.model_dump(mode="json"), request.y_axis.model_dump(mode="json"), request.series, digitizer_version, request.options)

    def get(self, key: str) -> DigitizationResult | None:
        path = self.directory / f"{key}.json"
        return DigitizationResult.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, result: DigitizationResult) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{key}.json"
        target.write_text(result.model_dump_json(exclude_none=True, indent=2), encoding="utf-8")
        return target
