"""Model-agnostic Figure Understanding V1 provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
import os
import time

from pydantic import ValidationError

from synthex_platform.visual.models import FigureRecord, FigureUnderstandingResult
from .cache import FigureUnderstandingCache


FIGURE_PROMPT_SCHEMA_VERSION = "figure_understanding_v1"
MAX_PROVIDER_ATTEMPTS = 3


class FigureUnderstandingProvider(ABC):
    provider_name: str
    model_name: str
    schema_version: str = FIGURE_PROMPT_SCHEMA_VERSION

    @abstractmethod
    def understand(self, image_png: bytes, figure: FigureRecord, page_context: str | None = None) -> FigureUnderstandingResult:
        """Return validated structure only; never digitized curve data."""


class GeminiFigureUnderstandingProvider(FigureUnderstandingProvider):
    """Optional Gemini adapter. It is never called unless a caller explicitly uses it."""

    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("google-genai is required for Gemini figure understanding.") from exc
        self._genai = genai
        self._types = types
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=self.api_key)

    def _prompt(self, figure: FigureRecord, page_context: str | None) -> str:
        return (
            "Interpret this one scientific figure. Return JSON only, matching the supplied schema. "
            "Do not digitize plotted curves or estimate data points. Capture only explicitly visible text annotations. "
            f"Figure caption: {figure.caption or 'unknown'}. Page context: {page_context or 'none'}. "
            "Allowed figure_type values: cycling_performance, charge_discharge, cyclic_voltammetry, eis_nyquist, "
            "tafel, polarization, xrd, raman, ftir, sem, tem, hrtem, xps, uv_vis, photoluminescence, dos, pdos, "
            "band_structure, heatmap, schematic, generic_plot, other, unknown. "
            "For annotations, preserve raw visible text and use figure_annotation provenance."
        )

    def understand(self, image_png: bytes, figure: FigureRecord, page_context: str | None = None) -> FigureUnderstandingResult:
        contents = [self._prompt(figure, page_context), self._types.Part.from_bytes(data=image_png, mime_type="image/png")]
        response = None
        for attempt in range(MAX_PROVIDER_ATTEMPTS):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=contents,
                    config={"response_mime_type": "application/json", "temperature": 0, "seed": 0,
                            "automatic_function_calling": {"disable": True}},
                )
                break
            except Exception:
                if attempt == MAX_PROVIDER_ATTEMPTS - 1:
                    raise
                time.sleep(2 ** attempt)
        if not response or not response.text:
            raise RuntimeError("Gemini returned no figure-understanding JSON.")
        try:
            return FigureUnderstandingResult.model_validate_json(response.text)
        except ValidationError as exc:
            raise RuntimeError("Gemini figure output failed local schema validation.") from exc


def apply_understanding(figure: FigureRecord, result: FigureUnderstandingResult, provider: FigureUnderstandingProvider) -> FigureRecord:
    """Copy interpreted fields onto a raw detected figure without changing archive data."""
    return figure.model_copy(update={
        "figure_type": result.figure_type, "raw_figure_type": result.raw_figure_type,
        "panels": result.panels or figure.panels, "axes": result.axes,
        "legend_entries": result.legend_entries, "annotations": result.annotations,
        "sample_material_labels": result.sample_material_labels, "context": result.context,
        "scientific_meaning": result.scientific_meaning, "understanding_provider": provider.provider_name,
        "provider_model": provider.model_name, "prompt_schema_version": provider.schema_version,
        "confidence": result.confidence, "warnings": [*figure.warnings, *result.warnings],
    })


def understand_with_cache(
    provider: FigureUnderstandingProvider, cache: FigureUnderstandingCache, source_checksum: str,
    figure: FigureRecord, image_png: bytes, page_context: str | None = None,
) -> FigureUnderstandingResult:
    """Use a caller-owned cache so identical figure/provider/schema calls are not repeated."""
    key = cache.key(source_checksum, figure.figure_id, provider.provider_name, provider.model_name, provider.schema_version)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = provider.understand(image_png, figure, page_context)
    cache.put(key, result)
    return result
